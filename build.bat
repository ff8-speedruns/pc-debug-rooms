@echo off
rem Local build of dist\FF8DebugRooms.exe -- same command the GitHub Action runs.
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name FF8DebugRooms --add-data "maplist;." debug_room_app.py
