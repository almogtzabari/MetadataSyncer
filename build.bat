@echo off
setlocal

:: ==========================================
::      DEPENDENCY SETUP - EXIFTOOL
:: ==========================================
echo Checking for dependencies...

:: Check if exiftool.exe exists. If it does, skip to the build part.
if exist "third_party\exiftool.exe" (
    echo ExifTool is already present.
    goto build
)

:: --- Download and Setup Logic ---
echo ExifTool not found. Downloading...

set EXIFTOOL_URL_64=https://exiftool.org/exiftool-13.43_64.zip
set EXIFTOOL_ZIP=exiftool.zip
set EXTRACT_DIR=third_party\exiftool_temp

:: Create the target directory
if not exist "third_party" mkdir "third_party"
if not exist "%EXTRACT_DIR%" mkdir "%EXTRACT_DIR%"

:: Download the file using PowerShell
echo Downloading from %EXIFTOOL_URL_64%...
powershell -command "Invoke-WebRequest -Uri '%EXIFTOOL_URL_64%' -OutFile '%EXIFTOOL_ZIP%'"

if not exist "%EXIFTOOL_ZIP%" (
    echo ERROR: Failed to download ExifTool. Please check your internet connection.
    pause
    exit /b 1
)

echo Extracting files...
powershell -command "Expand-Archive -Path '%EXIFTOOL_ZIP%' -DestinationPath '%EXTRACT_DIR%' -Force"

echo Renaming and moving executable...
set "SUBDIR="
for /d %%D in ("%EXTRACT_DIR%\exiftool*") do set "SUBDIR=%%D"
if not defined SUBDIR (
    echo ERROR: Could not find exiftool subdirectory in the archive.
    pause
    exit /b 1
)
set "EXIFTOOL_SOURCE_EXE=%SUBDIR%\\exiftool(-k).exe"
set "EXIFTOOL_SOURCE_DIR=%SUBDIR%\\exiftool_files"

powershell -command "$source_exe = '%EXIFTOOL_SOURCE_EXE%'; $dest_exe = 'third_party\\exiftool.exe'; $source_dir = '%EXIFTOOL_SOURCE_DIR%'; $dest_dir = 'third_party\\'; if (Test-Path $source_exe) { Move-Item -Path $source_exe -Destination $dest_exe; } else { Write-Host 'ERROR: Could not find exiftool(-k).exe in the archive.'; exit 1; }; if (Test-Path $source_dir) { Move-Item -Path $source_dir -Destination $dest_dir; } else { Write-Host 'ERROR: Could not find exiftool_files directory in the archive.'; exit 1; }"

if not exist "third_party\exiftool.exe" (
    echo ERROR: Failed to move exiftool executable.
    pause
    exit /b 1
)

echo Cleaning up...
del "%EXIFTOOL_ZIP%"
rmdir /s /q "%EXTRACT_DIR%"

echo Dependency setup complete.


:build
echo.

echo ==========================================
echo      METADATA SYNCER - BUNDLED BUILD
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
 --add-data "assets/app_icon.ico;." ^
 --add-data "third_party;third_party" ^
 "src/metadata_syncer.pyw"

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
endlocal
