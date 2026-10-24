@echo off
setlocal
rem Mo WebUI, kem bot Telegram o cua so rieng neu da cau hinh bot_token.
call "%~dp0scripts\env.bat" || goto :fail

"%PYTHON%" -I "%PROJECT_DIR%\scripts\has_telegram_token.py" >nul 2>&1
if errorlevel 1 goto :no_bot
echo ***** Telegram bot: dang khoi dong o cua so rieng... *****
start "MoneyPrinterPro Telegram Bot" cmd /c call "%~dp0telegram_bot.bat"
goto :run_webui

:no_bot
echo ***** Telegram bot: chua cau hinh [telegram].bot_token trong config.toml, bo qua. *****

:run_webui
call "%~dp0webui.bat"
exit /b %errorlevel%

:fail
pause
exit /b 1
