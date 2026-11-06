@echo off
chcp 65001 >nul
rem Starts background updates: matches every minute, events hourly, ranking daily.
rem Keep this window open while the site is running.
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python manage.py import_pandascore
python manage.py sync_vrs
python manage.py run_workers
pause
