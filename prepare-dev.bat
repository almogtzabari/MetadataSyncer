@echo off
setlocal

:: ==========================================
::      DEPENDENCY SETUP - EXIFTOOL
:: ==========================================
echo Checking for dependencies...

:: Check if exiftool.exe exists. If it does, we are done.
if exist "third_party\exiftool.exe" (
    echo ExifTool is already present.
    goto :eof
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
set "EXIFTOOL_SOURCE_EXE=%SUBDIR%\exiftool(-k).exe"
set "EXIFTOOL_SOURCE_DIR=%SUBDIR%\exiftool_files"

powershell -command "$source_exe = '%EXIFTOOL_SOURCE_EXE%'; $dest_exe = 'third_party\exiftool.exe'; $source_dir = '%EXIFTOOL_SOURCE_DIR%'; $dest_dir = 'third_party\'; if (Test-Path $source_exe) { Move-Item -Path $source_exe -Destination $dest_exe; } else { Write-Host 'ERROR: Could not find exiftool(-k).exe in the archive.'; exit 1; }; if (Test-Path $source_dir) { Move-Item -Path $source_dir -Destination $dest_dir; } else { Write-Host 'ERROR: Could not find exiftool_files directory in the archive.'; exit 1; }"

if not exist "third_party\exiftool.exe" (
    echo ERROR: Failed to move exiftool executable.
    pause
    exit /b 1
)

echo Cleaning up...
del "%EXIFTOOL_ZIP%"
rmdir /s /q "%EXTRACT_DIR%"

echo Dependency setup complete.

endlocal
