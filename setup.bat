@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
echo === PaperBot setup ===
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY (
  echo [!] Python not found. Install Python 3.10+ from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^) then run setup.bat again.
  pause & exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" || ( echo [!] Need Python 3.10 or newer & pause & exit /b 1 )
if not exist .venv ( %PY% -m venv .venv || ( echo [!] venv failed & pause & exit /b 1 ) )
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt || ( echo [!] pip install failed & pause & exit /b 1 )
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo [1/3] Notepad will open .env  -  paste your PAPER key ID and secret, save, close Notepad.
  notepad .env
)
echo.
echo [2/3] Checking Alpaca connection...
.venv\Scripts\python.exe bot.py check || ( echo [!] Check failed - fix .env then run setup.bat again & pause & exit /b 1 )
echo.
echo [3/3] First evolution run (finding rules)...
.venv\Scripts\python.exe evolve.py
echo.
echo Registering Windows scheduled tasks...
schtasks /Create /F /TN "PaperBot-daily" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 21:45 /TR "\"%~dp0run.bat\"" >nul && echo   - PaperBot-daily : Mon-Fri 21:45 (after US market open)
schtasks /Create /F /TN "PaperBot-evolve" /SC WEEKLY /D SAT /ST 10:00 /TR "\"%~dp0evolve.bat\"" >nul && echo   - PaperBot-evolve: Saturday 10:00
echo.
echo Done. Laptop must be ON and logged in at those times. Open dashboard.bat any time.
start "" "%~dp0data\dashboard.html"
pause
