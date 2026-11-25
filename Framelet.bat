@echo off
cd /d "%~dp0"
title Framelet
python -c "import PySide6, mss, imageio_ffmpeg, win32clipboard" >nul 2>nul
if errorlevel 1 (
    echo Framelet requires Python and the project dependencies.
    echo Run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
where pythonw >nul 2>nul
if errorlevel 1 (
    start "" /min python "%~dp0main.py"
) else (
    start "" pythonw "%~dp0main.py"
)
exit /b 0
