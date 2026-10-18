@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 goto runpy
where python >nul 2>&1
if %errorlevel%==0 goto runpython
echo Install Python 3.11 or newer from https://www.python.org/downloads/ and run this again.
echo During setup, enable "Add python.exe to PATH".
set EXITCODE=1
goto finish
:runpy
py -3 install.py %*
set EXITCODE=%errorlevel%
goto finish
:runpython
python install.py %*
set EXITCODE=%errorlevel%
:finish
echo %cmdcmdline% | findstr /i /c:"%~nx0" >nul
if not errorlevel 1 pause
exit /b %EXITCODE%
