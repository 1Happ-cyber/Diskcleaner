@echo off
cd /d "%~dp0"
REM Default: onedir (no runtime extraction, works even if TEMP is restricted).
REM Optional: build.bat onefile  -> single exe (needs a writable %TEMP% at run time).
set "MODE=--onedir"
set "OUT=dist\DiskCleaner\DiskCleaner.exe"
if /i "%~1"=="onefile" (
    set "MODE=--onefile"
    set "OUT=dist\DiskCleaner.exe"
)
REM PyInstaller needs an official Python build: Anaconda's Tcl/Tk layout is not found by the Tk hook.
set "PYTHON="
python -c "import sys, os; sys.exit(0 if not os.path.exists(os.path.join(sys.base_prefix, 'conda-meta')) else 1)" >nul 2>nul && set "PYTHON=python"
if not defined PYTHON (
    py -3 -c "import sys, os; sys.exit(0 if not os.path.exists(os.path.join(sys.base_prefix, 'conda-meta')) else 1)" >nul 2>nul && set "PYTHON=py -3"
)
if not defined PYTHON (
    echo [ERROR] No official Python found. Anaconda's Python cannot package Tk with PyInstaller.
    echo         Install python.org Python 3.12+ with Tcl/Tk, then run build.bat again.
    pause
    exit /b 1
)
if not exist .venv-build\Scripts\python.exe (
    echo Creating build virtual environment with: %PYTHON%
    %PYTHON% -m venv .venv-build
    if errorlevel 1 goto fail
)
.venv-build\Scripts\python.exe -m pip install --disable-pip-version-check --timeout 20 -r requirements.txt "pyinstaller>=6.16,<7"
if errorlevel 1 (
    echo Official index failed, retrying with a mirror...
    .venv-build\Scripts\python.exe -m pip install --disable-pip-version-check --timeout 20 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt "pyinstaller>=6.16,<7"
    if errorlevel 1 goto fail
)
.venv-build\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto fail
.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --clean %MODE% --windowed --name DiskCleaner --collect-submodules send2trash main.py
if errorlevel 1 goto fail
echo Build complete: %OUT%
pause
exit /b 0
:fail
echo Build failed. See output above.
pause
exit /b 1
