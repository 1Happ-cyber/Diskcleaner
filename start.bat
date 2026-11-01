@echo off
cd /d "%~dp0"
set "PYTHON="
py -3 -c "import sys" >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON (
    python -c "import sys" >nul 2>nul && set "PYTHON=python"
)
if not defined PYTHON (
    python3 -c "import sys" >nul 2>nul && set "PYTHON=python3"
)
if not defined PYTHON (
    echo [ERROR] Python 3.12+ not found. Install Python with Tcl/Tk, then retry.
    pause
    exit /b 1
)
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto fail
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --timeout 20 -r requirements.txt
if errorlevel 1 (
    echo Official index failed, retrying with a mirror...
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check --timeout 20 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
    if errorlevel 1 goto fail
)
.venv\Scripts\python.exe main.py
if errorlevel 1 goto fail
exit /b 0
:fail
echo [ERROR] Startup failed. Check the output above.
pause
exit /b 1
