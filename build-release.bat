@echo off
setlocal
cd /d "%~dp0"
title Build Framelet

py -3.12 -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo Missing build dependency.
    echo Run: py -3.12 -m pip install "PySide6==6.8.3" "PyInstaller==6.16.0" -r requirements.txt
    pause
    exit /b 1
)

py -3.12 -m pip install "PySide6==6.8.3" "PyInstaller==6.16.0"
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

py -3.12 icon_builder.py "Framelet.png" "Framelet.ico"
if errorlevel 1 (
    echo Icon generation failed.
    pause
    exit /b 1
)

if exist "dist\Framelet" rmdir /s /q "dist\Framelet"
if exist "dist\Framelet.exe" del /q "dist\Framelet.exe"
if exist "dist\Framelet-3.3-Windows-x64.zip" del /q "dist\Framelet-3.3-Windows-x64.zip"
if exist "dist\Framelet-3.3-Windows-x64.zip.sha256" del /q "dist\Framelet-3.3-Windows-x64.zip.sha256"

py -3.12 -m PyInstaller --noconfirm --clean --onedir --noupx --windowed --name Framelet --icon "Framelet.ico" --version-file "version_info.txt" --add-data "Framelet.png;." --add-data "support-qr.png;." --add-data "lucide;lucide" --collect-all imageio_ffmpeg --hidden-import win32clipboard --hidden-import win32con main.py
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

copy /y "DISTRIBUTION.md" "dist\Framelet\DISTRIBUTION.md" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -LiteralPath 'dist\Framelet' -DestinationPath 'dist\Framelet-3.3-Windows-x64.zip' -Force"
if errorlevel 1 (
    echo ZIP creation failed.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { $p='dist\Framelet-3.3-Windows-x64.zip'; $s=[IO.File]::OpenRead($p); try { $sha=[Security.Cryptography.SHA256]::Create(); $h=[BitConverter]::ToString($sha.ComputeHash($s)).Replace('-','').ToLowerInvariant() } finally { $s.Dispose() }; [IO.File]::WriteAllText('dist\Framelet-3.3-Windows-x64.zip.sha256', $h + '  Framelet-3.3-Windows-x64.zip' + [Environment]::NewLine, [Text.Encoding]::ASCII) } catch { Write-Error $_; exit 1 }"
if errorlevel 1 (
    echo Hash creation failed.
    pause
    exit /b 1
)

echo.
echo Ready: %~dp0dist\Framelet-3.3-Windows-x64.zip
echo Send the ZIP. Do not send Framelet.exe without its folder.
pause
