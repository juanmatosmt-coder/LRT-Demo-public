@echo off
rem Lab Request Assistant - one-time setup.
rem   install.bat         the app (form, chat, quality check); needs only Python 3.10+, no packages
rem   install.bat model   also the local AI model: GPU packages and the Qwen download (several GB, NVIDIA GPU)
rem Internet is used only here, to install packages and download the model once. At run time nothing leaves the PC.
setlocal
cd /d "%~dp0"

echo.
echo === Lab Request Assistant: install ===
set "LRTVER=unknown"
if exist VERSION set /p LRTVER=<VERSION
echo Version %LRTVER%

rem 1. Find Python (3.12 preferred). Not needed when .venv already exists.
if exist ".venv\Scripts\python.exe" ( echo Using the existing .venv & goto venv )
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo Python was not found. Install Python 3.12 from python.org ^(tick "Add python.exe to PATH"^), then run this again.
  pause & exit /b 1
)
echo Python: & %PY% --version

rem 2. The project's environment (.venv). An existing one is kept as it is.
echo Creating .venv ...
%PY% -m venv .venv || ( echo Could not create .venv. & pause & exit /b 1 )
:venv
set "VPY=.venv\Scripts\python.exe"
%VPY% --version
%VPY% -m pip install --upgrade pip --quiet

rem 3. Non-AI self-check: version, data, quality check, guardrails, local-only rules, web server (the AI model is NOT used)
echo.
%VPY% tools\selfcheck.py || ( echo NON-AI SELF-CHECK FAILED. See the messages above. & pause & exit /b 1 )

if /i not "%1"=="model" goto done

rem 4. Optional: the local AI model. If local_settings.bat points at one already installed elsewhere, only check it.
if exist local_settings.bat call local_settings.bat
if defined LRT_MODEL_PYTHON (
  echo.
  echo Using the AI model installed at: %LRT_MODEL_PYTHON%
  "%LRT_MODEL_PYTHON%" tools\launcher.py has-model || ( echo That install is not usable. See the messages above. & pause & exit /b 1 )
  goto done
)
echo.
echo Installing the AI model packages (CUDA 12.6 build of torch) ...
%VPY% -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126 || goto fail
%VPY% -m pip install transformers accelerate sentence-transformers bitsandbytes pillow fastapi uvicorn || goto fail
%VPY% tools\launcher.py gpu || ( echo The GPU is not visible to torch. Check the NVIDIA driver, then run "install.bat model" again. & pause & exit /b 1 )
echo Downloading the model once ...
%VPY% tools\launcher.py prefetch || goto fail
%VPY% tools\launcher.py has-model || ( echo The model files were not found after the download. See the messages above. & pause & exit /b 1 )

:done
echo.
echo Setup complete.
echo   start.bat         open the tool (uses the local AI model if it is installed)
echo   start.bat demo    open the tool without the AI model (rules only), for a quick look
if /i not "%1"=="model" echo   install.bat model add the local AI model (NVIDIA GPU, several GB)
echo.
pause
exit /b 0

:fail
echo.
echo Installation stopped. See the messages above.
pause
exit /b 1
