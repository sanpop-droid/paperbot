@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python.exe evolve.py >> data\evolve.log 2>&1
