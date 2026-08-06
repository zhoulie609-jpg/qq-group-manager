@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name QQGroupManager --collect-submodules websocket main.py
echo.
echo Build complete: dist\QQGroupManager.exe
pause

