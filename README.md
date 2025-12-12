# Metadata Syncer Pro

**Metadata Syncer Pro** is a professional Python-based GUI tool designed to restore missing metadata to rendered video files.

Video editors (like DaVinci Resolve or Premiere Pro) often strip essential metadata—such as the original creation date, GPS location, and camera technical details—during export. This tool copies that data from the original source file to the new rendered file, ensuring correct sorting and display in **Windows Explorer**, **QuickTime**, **Google Photos**, and **Immich**.

---

## ✨ Key Features

* **Smart Date Sync:** Copies original "Media Created" timestamp and calculates correct offsets.
* **Auto-Detect Timezone:** Automatically detects the correct Timezone based on the video's GPS coordinates.
* **Location Recovery:** Copies GPS coordinates and provides a **Live Preview** with a real-world address (Reverse Geocoding).
* **Camera Tech Data:** Restores camera make, model, ISO, aperture (F-Stop), and shutter speed.
* **Modern UI:** Dark mode interface with Drag & Drop support and a visual difference preview.

---

## 📂 Folder Structure (For Developers)

This project relies on a specific structure for development and building:

* **`src/`**: Contains the Python source code (`metadata_syncer.pyw`).
* **`assets/`**: Contains UI resources like `app_icon.ico`.
* **`third_party/`**: Contains `exiftool.exe` and its dependency folder `exiftool_files`.
    * *Note: These files are bundled INSIDE the final EXE during the build process.*

---

## 🚀 How to Use (For Users)

1.  Get the **`MetadataSyncerPro.exe`** file.
2.  **That's it!** The file is completely portable (Single-File). No installation required.
3.  Double-click to launch.
4.  **Source Video:** Drag & drop your original camera footage.
5.  **Target Video:** Drag & drop your rendered/edited file.
6.  **Review Data:**
    * The tool will automatically suggest a Timezone if GPS is found.
    * Use the **Checkboxes** to select what data to copy (Date, Location, Camera Info).
    * Check the **Preview Panel** to see the address and date calculations.
7.  Click **SYNC METADATA NOW**.

---

## 🛠️ Development

If you want to modify the code or build it yourself:

### 1. Prerequisites
Open a terminal in the root folder and install the required libraries:

```bash
pip install PyQt6 pyinstaller tzdata geopy timezonefinder
```