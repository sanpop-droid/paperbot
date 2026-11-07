@echo off
schtasks /Delete /F /TN "PaperBot-daily"
schtasks /Delete /F /TN "PaperBot-evolve"
echo Scheduled tasks removed. (Files and data are kept.)
pause
