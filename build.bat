@echo off
echo ==========================================
echo      METADATA SYNCER PRO - BUNDLED BUILD
echo ==========================================

:: 1. Clean previous builds
echo [1/3] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "MetadataSyncer.spec" del "MetadataSyncer.spec"

:: 2. Run PyInstaller with embedded data
:: --add-data "SourcePath;DestPath" (On Windows use semicolon ;)
:: We are telling it: Take 'third_party' folder and put it inside the EXE at 'third_party'
echo [2/3] Compiling Single-File EXE (This may take a minute)...

pyinstaller --noconsole --onefile ^
 --name "MetadataSyncer" ^
 --icon="assets\app_icon.ico" ^
 --add-data "assets\app_icon.ico;." ^
 --add-data "third_party;third_party" ^
 "src\metadata_syncer.pyw"

:: 3. Cleanup build folder (No need to copy third_party anymore!)
echo [3/3] Cleaning up temp files...
if exist "build" rmdir /s /q "build"
if exist "MetadataSyncer.spec" del "MetadataSyncer.spec"

echo ==========================================
echo      BUILD SUCCESSFUL!
echo      You now have a SINGLE file in: dist\MetadataSyncer.exe
echo      (It contains exiftool inside it)
echo ==========================================
pause