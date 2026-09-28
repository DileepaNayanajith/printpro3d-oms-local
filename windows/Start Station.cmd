@echo off
cd /d "%~dp0\.."
if not exist ".venv-windows\Scripts\python.exe" (
 echo Please run windows\Setup.cmd first.
 pause
 exit /b 1
)
start "PRINTPRO3D Printer" ".venv-windows\Scripts\python.exe" -u home_worker.py --kind print
start "PRINTPRO3D FDE" ".venv-windows\Scripts\python.exe" -u home_worker.py --kind fde
start "PRINTPRO3D WhatsApp" ".venv-windows\Scripts\python.exe" -u home_worker.py --kind whatsapp
