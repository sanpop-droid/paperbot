@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python.exe bot.py run >> data\run.log 2>&1
