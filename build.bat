@echo off
setlocal

:: ==========================================
::      SETUP & BUILD FOR METADATA SYNCER
:: ==========================================

:: 1. Prepare Dependencies
echo [1/4] Preparing dependencies...
call prepare-dev.bat
if not exist "third_party\exiftool.exe" (
    echo ERROR: Dependency setup failed. ExifTool not found.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo      METADATA SYNCER - BUNDLED BUILD
echo ==========================================

:: 2. Clean previous builds
echo [2/4] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "MetadataSyncer.spec" del "MetadataSyncer.spec"

:: 3. Run PyInstaller with embedded data
:: --add-data "SourcePath;DestPath" (On Windows use semicolon ;)
:: We are telling it: Take 'third_party' folder and put it inside the EXE at 'third_party'
echo [3/4] Compiling Single-File EXE (This may take a minute)...

pyinstaller --noconsole --onefile ^
 --name "MetadataSyncer" ^
 --icon="assets\app_icon.ico" ^
 --add-data "assets/app_icon.ico;." ^
 --add-data "third_party;third_party" ^
 "src/metadata_syncer.pyw"

:: 4. Cleanup build folder (No need to copy third_party anymore!)
echo [4/4] Cleaning up temp files...
if exist "build" rmdir /s /q "build"
if exist "MetadataSyncer.spec" del "MetadataSyncer.spec"

echo ==========================================
echo      BUILD SUCCESSFUL!
echo      You now have a SINGLE file in: dist\MetadataSyncer.exe
echo      (It contains exiftool inside it)
echo ==========================================
pause
endlocal