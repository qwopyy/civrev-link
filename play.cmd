@echo off
setlocal
cd /d "%~dp0"
set "PYFILE=%TEMP%\civrev-python-path.txt"
del "%PYFILE%" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure_python.ps1" "%PYFILE%"
if errorlevel 1 (
    echo Could not find Python.
    set EXITCODE=1
    goto finish
)
set /p PYTHON=<"%PYFILE%"
"%PYTHON%" -u play.py %*
set EXITCODE=%errorlevel%
:finish
echo %cmdcmdline% | findstr /i /c:"%~nx0" >nul
if not errorlevel 1 pause
exit /b %EXITCODE%
