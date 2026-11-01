@echo off
cd /d "%~dp0"
set "PYTHON="
if exist .venv\Scripts\python.exe set "PYTHON=.venv\Scripts\python.exe"
if not defined PYTHON (
    py -3 -c "import sys" >nul 2>nul && set "PYTHON=py -3"
)
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
%PYTHON% -m unittest discover -s tests -v
if errorlevel 1 goto fail
echo Tests passed.
pause
exit /b 0
:fail
echo Tests failed. Please save the output for investigation.
pause
exit /b 1
