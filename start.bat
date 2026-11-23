@echo off
rem Lab Request Assistant - start the tool and open it in the browser.
rem   start.bat         local AI model if installed (started in its own window), then the form page
rem   start.bat demo    no AI model: the assistant drafts by rules (quick look, any PC)
rem Everything listens on this computer only (127.0.0.1). Close the two windows, or run stop.bat, to stop.
setlocal
cd /d "%~dp0"
set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" ( echo Run install.bat first. & pause & exit /b 1 )
set "PAGE=http://127.0.0.1:8010/gui/request_form.html"
rem Optional local_settings.bat: use an AI model already installed in another folder (see local_settings.example.bat)
if exist local_settings.bat call local_settings.bat
set "MPY=%VPY%"
if defined LRT_MODEL_PYTHON set "MPY=%LRT_MODEL_PYTHON%"
if not exist "%MPY%" ( echo LRT_MODEL_PYTHON points at "%MPY%", which does not exist. Fix local_settings.bat. & pause & exit /b 1 )
%VPY% tools\launcher.py version

if /i "%1"=="demo" ( set "LRT_STUB_LLM=1" & echo Demo mode: no AI model. & goto gui )

rem An AI service set in local_settings.bat (for example Claude): no local model is started.
if defined LRT_BASE_URL (
  echo %LRT_BASE_URL% | findstr /i /c:"127.0.0.1" /c:"localhost" >nul || (
    echo AI service: %LRT_BASE_URL%  model: %LRT_AI_MODEL%
    if not defined LRT_AI_KEY echo WARNING: LRT_AI_KEY is not set. Run  setx LRT_AI_KEY "your-key"  and open a new window.
    echo Messages and drafts are sent to that service. Use only data your organisation allows there.
    goto gui
  )
)

rem The local AI model: reuse it if already running, start it if installed, otherwise run without it.
%VPY% tools\launcher.py up http://127.0.0.1:8000/health 1 >nul && ( echo The AI model is already running. & goto gui )
"%MPY%" tools\launcher.py has-model || ( echo The AI model is not installed: the assistant will draft by rules. Run "install.bat model" to add it. & goto gui )
echo Starting the local AI model in its own window (loading takes 1-3 minutes) ...
start "LRT - AI model (Qwen)" "%MPY%" spikes\qwen_server.py
%VPY% tools\launcher.py up http://127.0.0.1:8000/health 600 && echo The AI model is ready. || echo The AI model did not start in time; the assistant drafts by rules until it does. Check its window.

:gui
%VPY% tools\launcher.py up %PAGE% 1 >nul && ( echo The tool is already running. & goto open )
echo Starting the tool ...
start "LRT - Lab Request Assistant" %VPY% gui\serve.py
%VPY% tools\launcher.py up %PAGE% 30 || ( echo The tool did not start. Check its window. & pause & exit /b 1 )

:open
start "" %PAGE%
echo.
echo Open: %PAGE%
echo To stop: close the "LRT" windows, or run stop.bat.
timeout /t 5 >nul
exit /b 0
