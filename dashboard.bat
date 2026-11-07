@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python.exe dashboard.py
start "" "%~dp0data\dashboard.html"
