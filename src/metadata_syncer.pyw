import sys
import subprocess
import zoneinfo
import os
import shutil
import json
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QMessageBox,
                             QFrame, QListWidget, QListWidgetItem, QAbstractItemView,
                             QSizePolicy, QStyle, QLineEdit, QCheckBox, QGridLayout, QDialog)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QSize, QThread, QPoint, QTimer
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QCursor

# --- Dependencies Check ---
try:
    from geopy.geocoders import Nominatim
    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False

try:
    from timezonefinder import TimezoneFinder
    TZFINDER_AVAILABLE = True
except ImportError:
    TZFINDER_AVAILABLE = False

# --- Configuration ---
APP_AUTHOR = "AlmogTools"
APP_NAME = "MetadataSyncer"

# --- Helpers ---


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "assets"))
    return os.path.join(base_path, relative_path)


def get_exiftool_path():
    """
    Finds exiftool.exe.
    Priority:
    1. Bundled inside the EXE (sys._MEIPASS) -> For Single-File Mode
    2. Next to the EXE -> Fallback
    3. Dev Mode (../third_party) -> When running from source
    4. System PATH
    """
    if getattr(sys, 'frozen', False):
        # --- EXE MODE ---
        # 1. Look inside the temp folder (Where PyInstaller unpacks --onefile)
        try:
            base_path = sys._MEIPASS
            bundled_path = os.path.join(
                base_path, "third_party", "exiftool.exe")
            if os.path.exists(bundled_path):
                return bundled_path
        except Exception:
            pass

        # 2. Fallback: Look right next to the .exe file
        application_path = os.path.dirname(sys.executable)
        external_path = os.path.join(application_path, "exiftool.exe")
        if os.path.exists(external_path):
            return external_path

    else:
        # --- DEV MODE ---
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_script_dir)
        dev_location = os.path.join(
            project_root, "third_party", "exiftool.exe")
        if os.path.exists(dev_location):
            return dev_location

    # --- PATH FALLBACK ---
    if shutil.which("exiftool"):
        return "exiftool"

    return None

# --- WORKER: File Analysis ---


class FileAnalyzerWorker(QThread):
    data_ready = pyqtSignal(dict)

    def __init__(self, file_path, exif_cmd):
        super().__init__()
        self.file_path = file_path
        self.exif_cmd = exif_cmd

    def run(self):
        result = {"date": None, "gps": None, "camera": None,
                  "tz_suggested": None, "error": None}
        if not self.exif_cmd:
            result["error"] = "ExifTool not found"
            self.data_ready.emit(result)
            return

        try:
            # We fetch more specific GPS tags to be sure
            tags = [
                "-CreationDate", "-CreateDate",
                "-GPSLatitude", "-GPSLongitude",
                "-Make", "-Model", "-FNumber", "-ISO", "-ExposureTime"
            ]
            cmd = [self.exif_cmd, "-n", "-json"] + tags + [self.file_path]

            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            res = subprocess.run(cmd, capture_output=True, text=True,
                                 creationflags=0x08000000 if sys.platform == "win32" else 0, encoding='utf-8', errors='ignore')

            if not res.stdout.strip():
                self.data_ready.emit(result)
                return

            try:
                data_list = json.loads(res.stdout)
                if not data_list:
                    self.data_ready.emit(result)
                    return
                metadata = data_list[0]
            except:
                self.data_ready.emit(result)
                return

            # Date
            d = metadata.get("CreationDate", metadata.get("CreateDate", None))
            if d:
                result["date"] = str(d)

            # GPS
            lat, lon = metadata.get(
                "GPSLatitude"), metadata.get("GPSLongitude")
            if lat is not None and lon is not None:
                try:
                    f_lat, f_lon = float(lat), float(lon)
                    result["gps"] = (f_lat, f_lon)
                    if TZFINDER_AVAILABLE:
                        try:
                            tf = TimezoneFinder(in_memory=True)
                            result["tz_suggested"] = tf.timezone_at(
                                lng=f_lon, lat=f_lat)
                        except:
                            pass
                except:
                    pass

            # Camera
            make, model = metadata.get("Make", ""), metadata.get("Model", "")
            fnum, iso = metadata.get("FNumber"), metadata.get("ISO")
            parts = []
            if make or model:
                name = f"{make} {model}".strip()
                parts.append(" ".join(dict.fromkeys(name.split())))
            if fnum:
                parts.append(f"f/{fnum}")
            if iso:
                parts.append(f"ISO {iso}")
            if parts:
                result["camera"] = " | ".join(parts)

        except Exception as e:
            result["error"] = str(e)
        self.data_ready.emit(result)

# --- WORKER: Geo ---


class GeoWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, lat, lon):
        super().__init__()
        self.lat = lat
        self.lon = lon

    def run(self):
        if not GEOPY_AVAILABLE:
            return
        try:
            geolocator = Nominatim(user_agent="MetadataSyncer")
            loc = geolocator.reverse(
                (self.lat, self.lon), language='en', timeout=5)
            if loc:
                parts = loc.address.split(", ")
                self.finished.emit(
                    ", ".join(parts[-3:]) if len(parts) > 3 else loc.address)
            else:
                self.finished.emit("Unknown Location")
        except:
            self.finished.emit("Network Error")

# --- UI Components ---


class TimezonePopup(QDialog):
    def __init__(self, parent=None, on_select=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.on_select = on_select
        self.setFixedSize(350, 250)
        self.setStyleSheet("QDialog { background-color: #252526; border: 1px solid #007fd4; } QLineEdit { background-color: #2d2d2d; color: white; padding: 8px; border: none; border-bottom: 1px solid #444; } QListWidget { background-color: #252526; color: white; border: none; } QListWidget::item:selected { background-color: #007fd4; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter timezones...")
        self.search_box.textChanged.connect(self.filter_list)
        layout.addWidget(self.search_box)
        self.list_widget = QListWidget()
        self.load_timezones()
        self.list_widget.itemClicked.connect(self.item_clicked)
        layout.addWidget(self.list_widget)

    def showEvent(self, event): super().showEvent(
        event); self.search_box.setFocus()

    def load_timezones(self):
        try:
            zones = sorted(list(zoneinfo.available_timezones()))
        except:
            zones = ["Asia/Jerusalem", "UTC"]
        for z in zones:
            self.list_widget.addItem(QListWidgetItem(z))

    def filter_list(self, text):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def item_clicked(self, item):
        if self.on_select:
            self.on_select(item.text())
        self.close()


class ModernTimezoneSelector(QPushButton):
    tzChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("Select Timezone")
        self.current_tz = "Asia/Jerusalem"
        self.clicked.connect(self.toggle_popup)
        self.setStyleSheet(
            "QPushButton { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 4px; padding: 10px; color: white; text-align: left; } QPushButton:hover { border: 1px solid #007fd4; }")
        self.popup = None
        self._block_open = False

    def toggle_popup(self):
        if self._block_open:
            self._block_open = False
            return
        if self.popup and self.popup.isVisible():
            self.popup.close()
            return
        self.popup = TimezonePopup(self, self.set_timezone)
        old_close = self.popup.closeEvent
        def new_close(event): self._block_open = True; QTimer.singleShot(
            200, lambda: setattr(self, '_block_open', False)); old_close(event)
        self.popup.closeEvent = new_close
        pos = self.mapToGlobal(QPoint(0, self.height()))
        self.popup.move(pos)
        self.popup.setFixedWidth(self.width())
        self.popup.show()

    def set_timezone(self, tz): self.current_tz = tz; self.setText(
        f"Timezone: {tz}"); self.tzChanged.emit()

    def get_timezone(self): return self.current_tz


class FileDropZone(QFrame):
    fileDropped = pyqtSignal(str)

    def __init__(self, title, icon_name, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.current_file = None
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        std_icon = self.style().standardIcon(icon_name)
        self.icon_label.setPixmap(std_icon.pixmap(QSize(48, 48)))
        self.layout.addWidget(self.icon_label)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("DropTitle")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.title_lbl)
        self.sub_lbl = QLabel("Click or Drag File Here")
        self.sub_lbl.setObjectName("DropSub")
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.sub_lbl)
        self.setMinimumSize(250, 180)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_file_dialog()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().polish(self)

    def dragLeaveEvent(self, event): self.setProperty(
        "dragActive", False); self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragActive", False)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.set_file(file_path)

    def open_file_dialog(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "", "Video Files (*.mp4 *.mov *.mkv *.avi)")
        if fname:
            self.set_file(fname)

    def set_file(self, file_path):
        self.current_file = file_path
        file_name = os.path.basename(file_path)
        self.title_lbl.setText(file_name)
        self.title_lbl.setObjectName("FileName")
        self.sub_lbl.setText("Ready")
        check_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_DialogApplyButton)
        self.icon_label.setPixmap(check_icon.pixmap(QSize(40, 40)))
        self.setProperty("state", "loaded")
        self.style().polish(self)
        self.fileDropped.emit(file_path)

    def get_file(self): return self.current_file

# --- Main App ---


class MetadataSyncerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v32")
        self.resize(850, 750)
        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
            QFrame#Card { background-color: #252526; border-radius: 12px; border: 1px solid #333333; }
            QFrame#DropZone { background-color: #2d2d2d; border: 2px dashed #555555; border-radius: 10px; }
            QFrame#DropZone:hover { border: 2px dashed #007fd4; background-color: #333333; }
            QFrame#DropZone[state="loaded"] { background-color: #2b3c4f; border: 2px solid #007fd4; }
            QFrame#DropZone > QLabel { border: none; background-color: transparent; }
            QLabel#DropTitle { font-weight: bold; font-size: 14px; color: #aaaaaa; }
            QLabel#FileName { font-weight: bold; font-size: 13px; color: #ffffff; }
            QFrame#PreviewCard { background-color: #1e1e1e; border-radius: 8px; border: 1px solid #3e3e3e; padding: 15px; }
            QLabel#PreviewHeader { font-size: 11px; font-weight: bold; color: #007fd4; letter-spacing: 1px; margin-bottom: 5px; }
            QLabel#RowTitle { font-size: 13px; font-weight: 600; color: #bbbbbb; }
            QLabel#RowContent { font-size: 13px; color: #ffffff; }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 18px; height: 18px; background-color: #2d2d2d; border: 1px solid #555; border-radius: 4px; }
            QCheckBox::indicator:checked { background-color: #007fd4; border: 1px solid #007fd4; image: url(none); }
            QPushButton#PrimaryButton { background-color: #007fd4; border: none; border-radius: 6px; font-weight: bold; font-size: 15px; padding: 12px; }
            QPushButton#PrimaryButton:hover { background-color: #0069b4; }
        """)

        icon_p = resource_path("app_icon.ico")
        if os.path.exists(icon_p):
            self.setWindowIcon(QIcon(icon_p))

        self.settings = QSettings(APP_AUTHOR, APP_NAME)
        self.exiftool_cmd = get_exiftool_path()
        self.analysis_thread = None
        self.geo_thread = None
        self.current_metadata = {}

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(30, 30, 30, 30)

        self.setup_header()
        self.setup_drop_zones()
        self.setup_timezone_selector()
        self.setup_preview_panel()
        self.setup_footer()
        self.load_settings()

    def setup_header(self):
        header = QLabel("Metadata Syncer")
        header.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: white;")
        self.main_layout.addWidget(header)
        sub = QLabel("Select Source and Target videos to sync timestamps.")
        sub.setStyleSheet("color: #aaaaaa; margin-bottom: 10px;")
        self.main_layout.addWidget(sub)

    def setup_drop_zones(self):
        files_frame = QFrame()
        files_frame.setObjectName("Card")
        layout = QHBoxLayout(files_frame)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        self.source_zone = FileDropZone(
            "Source Video", QStyle.StandardPixmap.SP_FileIcon)
        self.source_zone.fileDropped.connect(self.on_source_dropped)
        self.target_zone = FileDropZone(
            "Target Video", QStyle.StandardPixmap.SP_DirIcon)
        layout.addWidget(self.source_zone)
        layout.addWidget(QLabel(
            "➔", styleSheet="font-size: 24px; color: #555; border:none;"), 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.target_zone)
        self.main_layout.addWidget(files_frame)

    def setup_timezone_selector(self):
        self.main_layout.addSpacing(10)
        self.tz_selector = ModernTimezoneSelector()
        self.tz_selector.tzChanged.connect(self.refresh_ui_from_state)
        self.main_layout.addWidget(self.tz_selector)

    def setup_preview_panel(self):
        self.main_layout.addSpacing(10)
        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("PreviewCard")
        self.grid = QGridLayout(self.preview_frame)
        self.grid.setVerticalSpacing(12)
        self.grid.setHorizontalSpacing(15)
        self.grid.setColumnStretch(2, 1)

        self.chk_date = QCheckBox()
        self.chk_date.setChecked(True)
        self.chk_date.stateChanged.connect(self.refresh_ui_from_state)
        self.grid.addWidget(self.chk_date, 0, 0)
        self.grid.addWidget(
            QLabel("📅 Date & Time", styleSheet="font-size:16px; border:none;"), 0, 1)
        self.lbl_date = QLabel("Waiting for file...")
        self.lbl_date.setObjectName("RowContent")
        self.grid.addWidget(self.lbl_date, 0, 2)

        self.chk_gps = QCheckBox()
        self.chk_gps.setChecked(True)
        self.chk_gps.stateChanged.connect(self.refresh_ui_from_state)
        self.grid.addWidget(self.chk_gps, 1, 0)
        self.grid.addWidget(
            QLabel("📍 Location", styleSheet="font-size:16px; border:none;"), 1, 1)
        self.lbl_loc = QLabel("Waiting for file...")
        self.lbl_loc.setObjectName("RowContent")
        self.grid.addWidget(self.lbl_loc, 1, 2)

        self.chk_cam = QCheckBox()
        self.chk_cam.setChecked(True)
        self.chk_cam.stateChanged.connect(self.refresh_ui_from_state)
        self.grid.addWidget(self.chk_cam, 2, 0)
        self.grid.addWidget(
            QLabel("📷 Camera Info", styleSheet="font-size:16px; border:none;"), 2, 1)
        self.lbl_cam = QLabel("Waiting for file...")
        self.lbl_cam.setObjectName("RowContent")
        self.grid.addWidget(self.lbl_cam, 2, 2)
        self.main_layout.addWidget(self.preview_frame)

    def setup_footer(self):
        self.main_layout.addSpacing(15)
        btn = QPushButton("SYNC METADATA NOW")
        btn.setObjectName("PrimaryButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.run_sync)
        self.main_layout.addWidget(btn)

    def load_settings(self):
        self.tz_selector.set_timezone(
            self.settings.value("last_tz", "Asia/Jerusalem"))
        self.chk_date.setChecked(
            self.settings.value("copy_date", True, type=bool))
        self.chk_gps.setChecked(
            self.settings.value("copy_gps", True, type=bool))
        self.chk_cam.setChecked(
            self.settings.value("copy_cam", True, type=bool))

    def on_source_dropped(self, path):
        if self.analysis_thread and self.analysis_thread.isRunning():
            self.analysis_thread.quit()
            self.analysis_thread.wait()
        self.lbl_date.setText("Analyzing...")
        self.lbl_loc.setText("Analyzing...")
        self.lbl_cam.setText("Analyzing...")
        self.current_metadata = {}
        self.analysis_thread = FileAnalyzerWorker(path, self.exiftool_cmd)
        self.analysis_thread.data_ready.connect(self.on_analysis_finished)
        self.analysis_thread.start()

    def on_analysis_finished(self, data):
        self.current_metadata = data
        if data.get("error"):
            QMessageBox.warning(self, "Read Error", f"{data['error']}")
        if data.get("tz_suggested"):
            self.tz_selector.blockSignals(True)
            self.tz_selector.set_timezone(data["tz_suggested"])
            self.tz_selector.blockSignals(False)
        self.refresh_ui_from_state()

    def refresh_ui_from_state(self):
        if self.geo_thread and self.geo_thread.isRunning():
            self.geo_thread.quit()
            self.geo_thread.wait()
        source = self.source_zone.get_file()
        if not source:
            return

        if self.chk_date.isChecked():
            raw_date = self.current_metadata.get("date")
            if raw_date:
                try:
                    clean = raw_date[:19]
                    naive = datetime.strptime(clean, "%Y:%m:%d %H:%M:%S")
                    tz = self.tz_selector.get_timezone()
                    aware = naive.replace(tzinfo=zoneinfo.ZoneInfo(tz))
                    off = f"{aware.strftime('%z')[:3]}:{aware.strftime('%z')[3:]}"
                    self.lbl_date.setText(f"{clean} ➜ {clean}{off}")
                    self.lbl_date.setStyleSheet(
                        "color: #4CAF50; font-weight: bold;")
                except:
                    self.lbl_date.setText("Date Error")
                    self.lbl_date.setStyleSheet("color: #ff5555;")
            else:
                self.lbl_date.setText("No Date Found")
                self.lbl_date.setStyleSheet("color: #888;")
        else:
            self.lbl_date.setText("Disabled")
            self.lbl_date.setStyleSheet("color: #888;")

        if self.chk_gps.isChecked():
            gps = self.current_metadata.get("gps")
            if gps:
                lat, lon = gps
                addr = self.current_metadata.get("address_cached")
                if addr:
                    self.lbl_loc.setText(f"{addr} ({lat:.4f}, {lon:.4f})")
                else:
                    self.lbl_loc.setText(
                        f"Resolving... ({lat:.4f}, {lon:.4f})")
                    self.geo_thread = GeoWorker(lat, lon)
                    self.geo_thread.finished.connect(self.on_address_ready)
                    self.geo_thread.start()
                self.lbl_loc.setStyleSheet("color: white;")
            else:
                self.lbl_loc.setText("No GPS Data")
                self.lbl_loc.setStyleSheet("color: #888;")
        else:
            self.lbl_loc.setText("Disabled")
            self.lbl_loc.setStyleSheet("color: #888;")

        if self.chk_cam.isChecked():
            cam = self.current_metadata.get("camera")
            if cam:
                self.lbl_cam.setText(cam)
                self.lbl_cam.setStyleSheet("color: white;")
            else:
                self.lbl_cam.setText("No Camera Data")
                self.lbl_cam.setStyleSheet("color: #888;")
        else:
            self.lbl_cam.setText("Disabled")
            self.lbl_cam.setStyleSheet("color: #888;")

    def on_address_ready(self, address):
        self.current_metadata["address_cached"] = address
        gps = self.current_metadata.get("gps")
        if gps and self.chk_gps.isChecked():
            self.lbl_loc.setText(f"{address} ({gps[0]:.4f}, {gps[1]:.4f})")

    def run_sync(self):
        src, tgt = self.source_zone.get_file(), self.target_zone.get_file()
        tz = self.tz_selector.get_timezone()
        if not self.exiftool_cmd:
            QMessageBox.critical(self, "Error", "ExifTool missing.")
            return
        if not src or not tgt:
            QMessageBox.warning(self, "Error", "Select files.")
            return

        self.settings.setValue("last_tz", tz)
        self.settings.setValue("copy_date", self.chk_date.isChecked())
        self.settings.setValue("copy_gps", self.chk_gps.isChecked())
        self.settings.setValue("copy_cam", self.chk_cam.isChecked())

        cmd = [self.exiftool_cmd]
        if self.chk_date.isChecked() and self.current_metadata.get("date"):
            try:
                raw = self.current_metadata["date"][:19]
                naive = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
                aware = naive.replace(tzinfo=zoneinfo.ZoneInfo(tz))
                utc = aware.astimezone(zoneinfo.ZoneInfo(
                    "UTC")).strftime("%Y:%m:%d %H:%M:%S")
                off = f"{aware.strftime('%z')[:3]}:{aware.strftime('%z')[3:]}"
                local = f"{raw}{off}"
                cmd.extend([f"-QuickTime:CreationDate={local}", f"-QuickTime:CreateDate={utc}",
                           f"-QuickTime:ModifyDate={utc}", f"-FileCreateDate={local}", f"-FileModifyDate={local}"])
            except:
                pass

        # --- FIX: CATCH-ALL GPS TAGS ---
        if self.chk_gps.isChecked():
            # This copies everything containing 'GPS' from source to target
            # Covers: QuickTime:GPSCoordinates, Keys:GPSCoordinates, etc.
            cmd.extend(["-TagsFromFile", src, "-*GPS*"])

        if self.chk_cam.isChecked():
            cmd.extend(["-TagsFromFile", src, "-Make", "-Model", "-FNumber",
                       "-ISO", "-ExposureTime", "-LensModel", "-LensID"])
        cmd.extend(["-overwrite_original", tgt])

        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(
                cmd, check=True, creationflags=0x08000000 if sys.platform == "win32" else 0)
            QMessageBox.information(self, "Success", "Synced!")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def closeEvent(self, event):
        if self.analysis_thread and self.analysis_thread.isRunning():
            self.analysis_thread.quit()
            self.analysis_thread.wait()
        if self.geo_thread and self.geo_thread.isRunning():
            self.geo_thread.quit()
            self.geo_thread.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon_p = resource_path("app_icon.ico")
    if os.path.exists(icon_p):
        app.setWindowIcon(QIcon(icon_p))
    window = MetadataSyncerApp()
    window.show()
    sys.exit(app.exec())
