@echo off
set "CURRENT_DIR=%~dp0"
echo ***** Current directory: %CURRENT_DIR% *****
rem Ban nay khong ket noi GitHub: khong tai code moi (git pull), chi cai/cap nhat thu vien Python.
rem Nguon ma goc: https://github.com/harry0703/MoneyPrinterTurbo

%CURRENT_DIR%\lib\python\Scripts\pip.exe install -r %CURRENT_DIR%MoneyPrinterTurbo\requirements.txt

echo ##### Update completed #####
pause
