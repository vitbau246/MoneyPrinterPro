@echo off
setlocal
rem Chi chay bot Telegram.
call "%~dp0scripts\env.bat" || goto :fail
cd /d "%PROJECT_DIR%"
"%PYTHON%" "%PROJECT_DIR%\telegram_bot.py" %*
if errorlevel 1 pause
exit /b %errorlevel%

:fail
pause
exit /b 1
