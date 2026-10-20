@echo off
rem Loi tat: chay start.bat trong thu muc ma nguon. File nay do scripts\env.bat tu tao, dung sua.
for /d %%D in ("%~dp0*") do if exist "%%~fD\scripts\env.bat" (call "%%~fD\start.bat" %* & exit /b)
echo ***** Khong tim thay thu muc ma nguon canh file nay. *****
pause
