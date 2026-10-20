@echo off
setlocal
rem Chay API: http://127.0.0.1:8080/docs
call "%~dp0scripts\env.bat" || goto :fail
cd /d "%PROJECT_DIR%"
"%PYTHON%" "%PROJECT_DIR%\main.py" %*
if errorlevel 1 pause
exit /b %errorlevel%

:fail
pause
exit /b 1
