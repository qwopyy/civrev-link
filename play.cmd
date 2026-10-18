@echo off
setlocal
cd /d "%~dp0"
set "PYFILE=%TEMP%\civrev-python-path.txt"
del "%PYFILE%" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure_python.ps1" "%PYFILE%"
if errorlevel 1 exit /b 1
set /p PYTHON=<"%PYFILE%"
"%PYTHON%" play.py %*
exit /b %errorlevel%
