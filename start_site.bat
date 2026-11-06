@echo off
chcp 65001 >nul
title XLTV 2.0 - site and auto updates
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
set AUTO_WORKERS=1
echo Starting XLTV 2.0 ...
echo Site: http://127.0.0.1:8000/  (data updates run in the background)
echo Keep this window open while you use the site. Close it to stop.
start "" cmd /c "timeout /t 6 >nul & start http://127.0.0.1:8000/"
python manage.py runserver 127.0.0.1:8000
pause
