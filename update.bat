@echo off
setlocal
rem Cai lai thu vien Python theo requirements.txt. Khong tai ma nguon moi.
rem Nguon ma goc: https://github.com/harry0703/MoneyPrinterTurbo
call "%~dp0scripts\env.bat" --force-install
if errorlevel 1 (
    pause
    exit /b 1
)
echo ##### Update completed #####
pause
