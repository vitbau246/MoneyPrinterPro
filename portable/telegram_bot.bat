@echo off
setlocal
set "CURRENT_DIR=%~dp0"
set "PROJECT_DIR=%CURRENT_DIR%MoneyPrinterTurbo"
echo ***** Current directory: %CURRENT_DIR% *****

cd /d "%PROJECT_DIR%"
set "PYTHONPATH=%PROJECT_DIR%"
set "PYTHONIOENCODING=utf-8"
set "FFMPEG_BINARY=%CURRENT_DIR%lib\ffmpeg\ffmpeg-7.0-essentials_build\ffmpeg.exe"
echo ***** FFmpeg file: %FFMPEG_BINARY% *****

"%CURRENT_DIR%lib\python\python.exe" -m pip show pyTelegramBotAPI >nul 2>&1 || "%CURRENT_DIR%lib\python\python.exe" -m pip install pyTelegramBotAPI==4.29.1

"%CURRENT_DIR%lib\python\python.exe" "%PROJECT_DIR%\telegram_bot.py"
if errorlevel 1 pause
