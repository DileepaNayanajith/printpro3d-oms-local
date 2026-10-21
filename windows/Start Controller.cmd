@echo off
cd /d "%LOCALAPPDATA%\PRINTPRO3D\Station"
.venv-windows\Scripts\python.exe -u station_controller.py
pause
