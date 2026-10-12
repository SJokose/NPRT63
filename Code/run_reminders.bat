@echo off
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" manage.py send_reminders >> reminders.log 2>&1