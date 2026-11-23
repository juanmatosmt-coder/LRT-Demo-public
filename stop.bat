@echo off
rem Stop the Lab Request Assistant: the tool (port 8010) and the local AI model (port 8000).
rem Works however the windows were opened (console windows or Windows Terminal tabs): it uses the servers' PID files
rem and the ports, and stops only Python processes.
setlocal
cd /d "%~dp0"
set "VPY=.venv\Scripts\python.exe"
if exist "%VPY%" ( %VPY% tools\launcher.py stop ) else ( py -3 tools\launcher.py stop 2>nul || python tools\launcher.py stop )
rem Older windows started before this version: close them by title too.
taskkill /fi "WINDOWTITLE eq LRT - Lab Request Assistant*" /t /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq LRT - AI model (Qwen)*" /t /f >nul 2>&1
timeout /t 2 >nul
