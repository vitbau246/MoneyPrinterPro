@echo off
setlocal
rem Mo WebUI, kem bot Telegram o cua so rieng neu da cau hinh bot_token.
call "%~dp0scripts\env.bat" || goto :fail

"%PYTHON%" -c "import os,sys,tomllib; c=tomllib.load(open(r'%PROJECT_DIR%\config.toml','rb')).get('telegram',{}); sys.exit(0 if (os.getenv('TELEGRAM_BOT_TOKEN') or c.get('bot_token')) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ***** Telegram bot: chua cau hinh [telegram].bot_token trong config.toml, bo qua. *****
) else (
    echo ***** Telegram bot: dang khoi dong o cua so rieng... *****
    start "MoneyPrinterPro Telegram Bot" cmd /c call "%~dp0telegram_bot.bat"
)

call "%~dp0webui.bat"
exit /b %errorlevel%

:fail
pause
exit /b 1
