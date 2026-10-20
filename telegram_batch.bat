@echo off
setlocal
rem Tao hang loat tu file chu de, vi du:
rem     telegram_batch.bat --preset dongluc --topics storage\batch\dongluc.txt
rem Chay lai cung lenh de tiep tuc.
call "%~dp0scripts\env.bat" || goto :fail
cd /d "%PROJECT_DIR%"
"%PYTHON%" "%PROJECT_DIR%\telegram_batch.py" %*
pause
exit /b %errorlevel%

:fail
pause
exit /b 1
