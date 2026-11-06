@echo off
chcp 65001 >nul
rem Запуск фоновых обновлений (матчи каждую минуту, события раз в час, рейтинг раз в сутки).
rem Окно должно оставаться открытым: пока оно работает, сайт получает новые матчи и результаты.
cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
python manage.py import_pandascore
python manage.py sync_vrs
python manage.py run_workers
pause
