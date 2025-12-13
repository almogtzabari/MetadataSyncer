import sys
import subprocess
import zoneinfo
import os
import shutil
import json
import argparse
import logging
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
APP_AUTHOR = "Almog Tzabari"
APP_NAME = "MetadataSyncer"
logger = logging.getLogger(__name__)

# Constants
DEFAULT_TIMEZONE = "UTC"
VIDEO_FILE_FILTERS = "Video Files (*.mp4 *.mov *.mkv *.avi)"

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
                logger.debug(f"ExifTool found in bundled path: {bundled_path}")
                return bundled_path
            logger.debug(f"ExifTool not found in bundled path: {bundled_path}")
        except Exception: # Broad exception here is acceptable as sys._MEIPASS can fail in various ways
            logger.debug("sys._MEIPASS not available or failed during ExifTool search.")
            pass

        # 2. Fallback: Look right next to the .exe file
        application_path = os.path.dirname(sys.executable)
        external_path = os.path.join(application_path, "exiftool.exe")
        if os.path.exists(external_path):
            logger.debug(f"ExifTool found next to executable: {external_path}")
            return external_path
        logger.debug(f"ExifTool not found next to executable: {external_path}")

    else:
        # --- DEV MODE ---
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_script_dir)
        dev_location = os.path.join(
            project_root, "third_party", "exiftool.exe")
        if os.path.exists(dev_location):
            logger.debug(f"ExifTool found in development location: {dev_location}")
            return dev_location
        logger.debug(f"ExifTool not found in development location: {dev_location}")

    # --- PATH FALLBACK ---
    if shutil.which("exiftool"):
        logger.debug("ExifTool found in system PATH.")
        return "exiftool"

    logger.warning("ExifTool not found in any expected location or system PATH.")
    return None


def analyze_file_metadata(file_path, exif_cmd):
    """
    Analyzes file metadata synchronously using ExifTool.
    Returns a dictionary with 'date', 'gps', 'camera', 'tz_suggested', 'error'.
    """
    logger.debug(f"Analyzing file metadata for: {file_path}")
    result = {"date": None, "gps": None, "camera": None,
              "tz_suggested": None, "error": None}
    if not exif_cmd:
        result["error"] = "ExifTool not found"
        logger.error(f"ExifTool not found when analyzing {file_path}")
        return result

    try:
        tags = [
            "-CreationDate", "-CreateDate",
            "-GPSLatitude", "-GPSLongitude",
            "-Make", "-Model", "-FNumber", "-ISO", "-ExposureTime"
        ]
        cmd = [exif_cmd, "-n", "-json"] + tags + [file_path]
        logger.debug(f"ExifTool command for analysis: {' '.join(cmd)}")

        res = subprocess.run(cmd, capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0, encoding='utf-8', errors='ignore')
        
        if res.returncode != 0:
            logger.warning(f"ExifTool analysis for {file_path} returned non-zero exit code {res.returncode}. Stderr: {res.stderr.strip()}")

        if not res.stdout.strip():
            logger.debug(f"ExifTool analysis for {file_path} returned no stdout.")
            return result

        try:
            data_list = json.loads(res.stdout)
            if not data_list:
                logger.debug(f"ExifTool JSON output for {file_path} was empty.")
                return result
            metadata = data_list[0]
            logger.debug(f"Successfully parsed metadata for {file_path}.")
        except json.JSONDecodeError as e:
            result["error"] = f"JSON decoding error: {e}"
            logger.error(f"JSON decoding error for {file_path}: {e}. Output: {res.stdout.strip()}")
            return result
        except IndexError: # For cases where data_list is empty after JSON parsing
            result["error"] = "No metadata found in JSON output."
            logger.warning(f"No metadata found in JSON output for {file_path}.")
            return result

        # Date
        d = metadata.get("CreationDate", metadata.get("CreateDate", None))
        if d:
            result["date"] = str(d)
            logger.debug(f"Found date {d} for {file_path}")

        # GPS
        lat, lon = metadata.get("GPSLatitude"), metadata.get("GPSLongitude")
        if lat is not None and lon is not None:
            try:
                f_lat, f_lon = float(lat), float(lon)
                result["gps"] = (f_lat, f_lon)
                logger.debug(f"Found GPS coordinates ({f_lat}, {f_lon}) for {file_path}")
                if TZFINDER_AVAILABLE:
                    try:
                        tf = TimezoneFinder(in_memory=True)
                        tz_suggested = tf.timezone_at(
                            lng=f_lon, lat=f_lat)
                        result["tz_suggested"] = tz_suggested
                        logger.debug(f"Suggested timezone for {file_path}: {tz_suggested}")
                    except Exception as e:
                        logger.warning(f"TimezoneFinder failed for {file_path}: {e}")
                else:
                    logger.debug(f"TimezoneFinder not available.")
            except ValueError as e:
                logger.warning(f"GPS coordinate conversion failed for {file_path}: {e}")

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
            logger.debug(f"Found camera info '{result['camera']}' for {file_path}")

    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"An unexpected error occurred during metadata analysis for {file_path}")
    logger.debug(f"Analysis complete for {file_path}. Result: {result}")
    return result


def perform_sync_operation(source_path, target_path, sync_date, sync_gps, sync_camera, timezone_str, exiftool_cmd, source_metadata_pre_analyzed=None):
    """
    Performs the metadata synchronization operation using ExifTool.
    Optionally accepts pre-analyzed source metadata to avoid redundant analysis.
    """
    logger.info(f"Initiating sync from '{os.path.basename(source_path)}' to '{os.path.basename(target_path)}'.")
    logger.debug(f"Sync options: date={sync_date}, gps={sync_gps}, camera={sync_camera}, timezone='{timezone_str}'")

    if not exiftool_cmd:
        logger.error("ExifTool not found. Cannot perform sync.")
        return False
    if not source_path or not target_path:
        logger.error("Both source and target file paths must be provided for sync.")
        return False

    # Use pre-analyzed metadata if available, otherwise analyze
    if source_metadata_pre_analyzed:
        source_metadata = source_metadata_pre_analyzed
        logger.debug("Using pre-analyzed source metadata.")
    else:
        logger.debug("Analyzing source file metadata for sync operation.")
        source_metadata = analyze_file_metadata(source_path, exiftool_cmd)
        if source_metadata.get("error"):
            logger.error(f"Error analyzing source file '{os.path.basename(source_path)}' for sync: {source_metadata['error']}")
            return False

    cmd = [exiftool_cmd]

    if sync_date and source_metadata.get("date"):
        try:
            raw = source_metadata["date"][:19]
            naive = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
            aware = naive.replace(tzinfo=zoneinfo.ZoneInfo(timezone_str))
            utc = aware.astimezone(zoneinfo.ZoneInfo(
                "UTC")).strftime("%Y:%m:%d %H:%M:%S")
            off = f"{aware.strftime('%z')[:3]}:{aware.strftime('%z')[3:]}"
            local = f"{raw}{off}"
            cmd.extend([f"-QuickTime:CreationDate={local}", f"-QuickTime:CreateDate={utc}",
                       f"-QuickTime:ModifyDate={utc}", f"-FileCreateDate={local}", f"-FileModifyDate={local}"])
            logger.debug(f"Added date sync commands for {os.path.basename(source_path)} (local: {local}, utc: {utc}).")
        except Exception as e:
            logger.warning(f"Could not sync date metadata from '{os.path.basename(source_path)}': {e}")
            pass

    if sync_gps:
        cmd.extend(["-TagsFromFile", source_path, "-*GPS*"])
        logger.debug(f"Added GPS sync commands for {os.path.basename(source_path)}.")

    if sync_camera:
        cmd.extend(["-TagsFromFile", source_path, "-Make", "-Model", "-FNumber",
                   "-ISO", "-ExposureTime", "-LensModel", "-LensID"])
        logger.debug(f"Added camera info sync commands for {os.path.basename(source_path)}.")

    cmd.extend(["-overwrite_original", target_path])
    logger.debug(f"Full ExifTool sync command: {' '.join(cmd)}")

    try:
        subprocess.run(
            cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )
        logger.info(f"Metadata successfully synced from '{os.path.basename(source_path)}' to '{os.path.basename(target_path)}'.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error during metadata sync to '{os.path.basename(target_path)}': {e}. Stderr: {e.stderr.strip()}")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred during sync to '{os.path.basename(target_path)}'.")
        return False




def get_effective_timezone(user_specified_tz, detected_tz_suggested):
    """
    Determines the effective timezone to use.
    If user_specified_tz is "UTC" (the default argparse value, indicating no explicit user input)
    and detected_tz_suggested is available, returns detected_tz_suggested.
    Otherwise, returns user_specified_tz.
    """
    if user_specified_tz == DEFAULT_TIMEZONE and detected_tz_suggested:
        return detected_tz_suggested
    return user_specified_tz


# --- WORKER: File Analysis ---


class FileAnalyzerWorker(QThread):
    data_ready = pyqtSignal(dict)

    def __init__(self, file_path, exif_cmd):
        super().__init__()
        self.file_path = file_path
        self.exif_cmd = exif_cmd

    def run(self):
        result = analyze_file_metadata(self.file_path, self.exif_cmd)
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
            logger.debug(f"Loaded {len(zones)} available timezones.")
        except Exception: # Catch specific exception if possible, or log it
            logger.exception("Failed to load available timezones. Using default list.")
            zones = [DEFAULT_TIMEZONE, "America/New_York", "Europe/London", "Asia/Tokyo"]
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
        self.current_tz = DEFAULT_TIMEZONE
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
            self, "Select Video", "", VIDEO_FILE_FILTERS)
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
        logger.debug("Initializing MetadataSyncerApp.")
        self.setWindowTitle(f"{APP_NAME}")
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
            logger.debug(f"Application icon loaded from: {icon_p}")
        else:
            logger.warning(f"Application icon not found at: {icon_p}")

        self.settings = QSettings(APP_AUTHOR, APP_NAME)
        self.exiftool_cmd = get_exiftool_path()
        logger.info(f"ExifTool command path: {self.exiftool_cmd}")
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
        logger.debug("MetadataSyncerApp initialization complete.")

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
            self.settings.value("last_tz", DEFAULT_TIMEZONE))
        self.chk_date.setChecked(
            self.settings.value("copy_date", True, type=bool))
        self.chk_gps.setChecked(
            self.settings.value("copy_gps", True, type=bool))
        self.chk_cam.setChecked(
            self.settings.value("copy_cam", True, type=bool))

    def on_source_dropped(self, path):
        logger.debug(f"Source file dropped: {path}")
        if self.analysis_thread and self.analysis_thread.isRunning():
            logger.debug("Existing analysis thread is running, quitting it.")
            self.analysis_thread.quit()
            self.analysis_thread.wait()
        self.lbl_date.setText("Analyzing...")
        self.lbl_loc.setText("Analyzing...")
        self.lbl_cam.setText("Analyzing...")
        self.current_metadata = {}
        self.analysis_thread = FileAnalyzerWorker(path, self.exiftool_cmd)
        self.analysis_thread.data_ready.connect(self.on_analysis_finished)
        self.analysis_thread.start()
        logger.debug(f"Started analysis thread for {path}.")

    def on_analysis_finished(self, data):
        logger.debug(f"Analysis finished. Data: {data}")
        self.current_metadata = data
        if data.get("error"):
            logger.error(f"Error during file analysis: {data['error']}")
            QMessageBox.warning(self, "Read Error", f"{data['error']}")
        if data.get("tz_suggested"):
            logger.debug(f"Suggested timezone from analysis: {data['tz_suggested']}")
            self.tz_selector.blockSignals(True)
            self.tz_selector.set_timezone(data["tz_suggested"])
            self.tz_selector.blockSignals(False)
        self.refresh_ui_from_state()

    def refresh_ui_from_state(self):
        logger.debug("Refreshing UI from state.")
        if self.geo_thread and self.geo_thread.isRunning():
            self.geo_thread.quit()
            self.geo_thread.wait()
            logger.debug("Existing geo-coding thread is running, quitting it.")
        source = self.source_zone.get_file()
        if not source:
            logger.debug("No source file selected, skipping UI refresh.")
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
                    logger.debug(f"Displaying date: {clean} with offset {off}")
                except Exception as e:
                    self.lbl_date.setText(f"Date Error: {e}")
                    self.lbl_date.setStyleSheet("color: #ff5555;")
                    logger.exception("Error processing date for UI refresh.")
            else:
                self.lbl_date.setText("No Date Found")
                self.lbl_date.setStyleSheet("color: #888;")
                logger.debug("No date found in metadata for UI refresh.")
        else:
            self.lbl_date.setText("Disabled")
            self.lbl_date.setStyleSheet("color: #888;")
            logger.debug("Date sync disabled, UI label set to 'Disabled'.")

        if self.chk_gps.isChecked():
            gps = self.current_metadata.get("gps")
            if gps:
                lat, lon = gps
                addr = self.current_metadata.get("address_cached")
                if addr:
                    self.lbl_loc.setText(f"{addr} ({lat:.4f}, {lon:.4f})")
                    logger.debug(f"Displaying cached address: {addr} ({lat:.4f}, {lon:.4f})")
                else:
                    self.lbl_loc.setText(
                        f"Resolving... ({lat:.4f}, {lon:.4f})")
                    self.geo_thread = GeoWorker(lat, lon)
                    self.geo_thread.finished.connect(self.on_address_ready)
                    self.geo_thread.start()
                    logger.debug(f"Started geo-coding thread for ({lat:.4f}, {lon:.4f}).")
                self.lbl_loc.setStyleSheet("color: white;")
            else:
                self.lbl_loc.setText("No GPS Data")
                self.lbl_loc.setStyleSheet("color: #888;")
                logger.debug("No GPS data found in metadata for UI refresh.")
        else:
            self.lbl_loc.setText("Disabled")
            self.lbl_loc.setStyleSheet("color: #888;")
            logger.debug("GPS sync disabled, UI label set to 'Disabled'.")

        if self.chk_cam.isChecked():
            cam = self.current_metadata.get("camera")
            if cam:
                self.lbl_cam.setText(cam)
                self.lbl_cam.setStyleSheet("color: white;")
                logger.debug(f"Displaying camera info: {cam}")
            else:
                self.lbl_cam.setText("No Camera Data")
                self.lbl_cam.setStyleSheet("color: #888;")
                logger.debug("No camera data found in metadata for UI refresh.")
        else:
            self.lbl_cam.setText("Disabled")
            self.lbl_cam.setStyleSheet("color: #888;")
            logger.debug("Camera sync disabled, UI label set to 'Disabled'.")

    def on_address_ready(self, address):
        logger.debug(f"Geo-coding finished. Address: {address}")
        self.current_metadata["address_cached"] = address
        gps = self.current_metadata.get("gps")
        if gps and self.chk_gps.isChecked():
            self.lbl_loc.setText(f"{address} ({gps[0]:.4f}, {gps[1]:.4f})")
            logger.debug(f"Updated UI with geo-coded address: {address}")

    def run_sync(self):
        src, tgt = self.source_zone.get_file(), self.target_zone.get_file()
        user_selected_tz = self.tz_selector.get_timezone()
        logger.info(f"User initiated sync. Source: '{src}', Target: '{tgt}', User TZ: '{user_selected_tz}'")
        
        if not self.exiftool_cmd:
            logger.critical("ExifTool command not found when attempting sync via GUI.")
            QMessageBox.critical(self, "Error", "ExifTool missing.")
            return
        if not src or not tgt:
            logger.warning("Source or target file not selected for GUI sync.")
            QMessageBox.warning(self, "Error", "Select files.")
            return

        # Resolve the effective timezone using the shared logic
        effective_tz = get_effective_timezone(user_selected_tz, self.current_metadata.get("tz_suggested"))
        logger.info(f"Effective timezone for sync: {effective_tz}")
        
        self.settings.setValue("last_tz", effective_tz) # Save the effective TZ for next time
        self.settings.setValue("copy_date", self.chk_date.isChecked())
        self.settings.setValue("copy_gps", self.chk_gps.isChecked())
        self.settings.setValue("copy_cam", self.chk_cam.isChecked())
        logger.debug("Saved current sync settings.")

        # Call the unified sync operation
        success = perform_sync_operation(
            source_path=src,
            target_path=tgt,
            sync_date=self.chk_date.isChecked(),
            sync_gps=self.chk_gps.isChecked(),
            sync_camera=self.chk_cam.isChecked(),
            timezone_str=effective_tz,
            exiftool_cmd=self.exiftool_cmd,
            source_metadata_pre_analyzed=self.current_metadata
        )

        if success:
            logger.info("Metadata sync completed successfully via GUI.")
            QMessageBox.information(self, "Success", "Synced!")
        else:
            logger.error("Metadata sync failed via GUI.")
            # Error messages are already printed by perform_sync_operation
            QMessageBox.critical(self, "Error", "Failed to sync metadata. Check console for details.")

    def closeEvent(self, event):
        logger.debug("Application close event triggered.")
        if self.analysis_thread and self.analysis_thread.isRunning():
            self.analysis_thread.quit()
            self.analysis_thread.wait()
            logger.debug("Analysis thread stopped.")
        if self.geo_thread and self.geo_thread.isRunning():
            self.geo_thread.quit()
            self.geo_thread.wait()
            logger.debug("Geo-coding thread stopped.")
        event.accept()
        logger.debug("Application closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync metadata between video files. If no specific sync flags are provided (--sync-date, --sync-gps, --sync-camera), all available metadata types will be synced by default.")
    parser.add_argument("--source", nargs='?', help="Path to the source video file (source).")
    parser.add_argument("--target", nargs='?', help="Path to the target video file (target).")
    parser.add_argument("--sync-date", action="store_true", help="Sync date and time metadata.")
    parser.add_argument("--sync-gps", action="store_true", help="Sync GPS location metadata.")
    parser.add_argument("--sync-camera", action="store_true", help="Sync camera information metadata.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help=f"Specify timezone for date syncing (e.g., 'Asia/Jerusalem'). Default is '{DEFAULT_TIMEZONE}'.")
    parser.add_argument("--log-level", type=str, default="INFO", 
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default is INFO.")
    parser.add_argument("--log-file", type=str, help="Specify a file to write debug logs to.")

    args = parser.parse_args()

    # Configure logging
    numeric_log_level = getattr(logging, args.log_level.upper(), None)
    if not isinstance(numeric_log_level, int):
        raise ValueError(f"Invalid log level: {args.log_level}")
    
    log_format = '%(asctime)s - %(levelname)s - %(message)s'

    if args.log_file:
        logging.basicConfig(level=numeric_log_level, format=log_format, datefmt='%Y-%m-%d %H:%M', filename=args.log_file, filemode='w')
    else:
        logging.basicConfig(level=numeric_log_level, format=log_format, datefmt='%Y-%m-%d %H:%M')

    logger.debug(f"Application started with arguments: {args}")

    # Determine if any sync flags were explicitly set
    any_sync_flag_set = args.sync_date or args.sync_gps or args.sync_camera

    # If no sync flags are set, enable all by default
    if not any_sync_flag_set:
        args.sync_date = True
        args.sync_gps = True
        args.sync_camera = True

    if args.source and args.target:
        # CLI Mode
        exiftool_cmd = get_exiftool_path()
        if not exiftool_cmd:
            logger.critical("ExifTool not found. Please ensure it's installed and accessible.")
            sys.exit(1)

        if not os.path.exists(args.source):
            logger.critical(f"Source file not found: {args.source}")
            sys.exit(1)
        if not os.path.exists(args.target):
            logger.critical(f"Target file not found: {args.target}")
            sys.exit(1)

        # Analyze source file for metadata to get suggested timezone
        source_metadata_cli = analyze_file_metadata(args.source, exiftool_cmd)
        if source_metadata_cli.get("error"):
            logger.critical(f"Error analyzing source file '{os.path.basename(args.source)}': {source_metadata_cli['error']}")
            sys.exit(1)

        # Determine timezone to use
        timezone_to_use = get_effective_timezone(args.timezone, source_metadata_cli.get("tz_suggested"))
        if timezone_to_use != args.timezone:
            logger.info(f"Automatically detected timezone from source file: {timezone_to_use}")

        logger.info(f"Starting metadata sync from '{os.path.basename(args.source)}' to '{os.path.basename(args.target)}'...")
        sync_types = []
        if args.sync_date:
            sync_types.append("Date")
        if args.sync_gps:
            sync_types.append("GPS")
        if args.sync_camera:
            sync_types.append("Camera")
        logger.info(f"Syncing: {', '.join(sync_types)}")
        logger.info(f"Timezone: {timezone_to_use}")

        success = perform_sync_operation(
            source_path=args.source,
            target_path=args.target,
            sync_date=args.sync_date,
            sync_gps=args.sync_gps,
            sync_camera=args.sync_camera,
            timezone_str=timezone_to_use,
            exiftool_cmd=exiftool_cmd,
            source_metadata_pre_analyzed=source_metadata_cli
        )
        sys.exit(0 if success else 1)
    else:
        # GUI Mode
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        # Icon is already set in MetadataSyncerApp constructor
        window = MetadataSyncerApp()
        window.show()
        sys.exit(app.exec())
