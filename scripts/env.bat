@echo off
rem Chuan bi moi truong chung cho cac file .bat. Goi tu file khac:
rem     call "%~dp0scripts\env.bat" [--force-install]
rem Dat cac bien PROJECT_DIR, PYTHON, PYTHONPATH, FFMPEG_BINARY cho file goi no.
rem - Python: lib\python cua ban portable, roi .venv; chua co (hoac .venv hong do copy tu may khac) thi tu tao lai tu Python 3.11 tro len.
rem - Tu cai thu vien lan dau va moi khi requirements.txt thay doi (hoac khi --force-install).
rem - Tu tao config.toml tu config.example.toml neu chua co.
rem - Ban portable: tu tao/cap nhat cac file .bat loi tat o thu muc ngoai (lay tu portable\).
rem Luu y: khong dung PowerShell va khong dat duong dan trong khoi ( ) de chay duoc ca khi duong dan co dau cach/ngoac.

for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"
for %%I in ("%PROJECT_DIR%\..") do set "PORTABLE_DIR=%%~fI"
set "IS_PORTABLE="
if exist "%PORTABLE_DIR%\lib\python\python.exe" set "IS_PORTABLE=1"

set "PYTHON="
if defined IS_PORTABLE set "PYTHON=%PORTABLE_DIR%\lib\python\python.exe"
if not defined PYTHON if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
if defined PYTHON call :check_python
if not defined PYTHON call :create_venv
if not defined PYTHON exit /b 1

set "PYTHONPATH=%PROJECT_DIR%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if not defined FFMPEG_BINARY if defined IS_PORTABLE call :find_portable_ffmpeg

if exist "%PROJECT_DIR%\config.toml" goto :config_ready
if not exist "%PROJECT_DIR%\config.example.toml" goto :config_ready
copy /y "%PROJECT_DIR%\config.example.toml" "%PROJECT_DIR%\config.toml" >nul
echo ***** Da tao config.toml tu config.example.toml *****
:config_ready

rem Ban sao requirements.txt da cai, nam ngay trong moi truong Python dang dung.
for %%I in ("%PYTHON%") do set "REQUIREMENTS_STAMP=%%~dpImpt-requirements.installed"
if /i "%~1"=="--force-install" del "%REQUIREMENTS_STAMP%" >nul 2>&1
fc /b "%PROJECT_DIR%\requirements.txt" "%REQUIREMENTS_STAMP%" >nul 2>&1
if errorlevel 1 call :install_requirements
if errorlevel 1 exit /b 1

if defined IS_PORTABLE call :sync_portable_launchers
exit /b 0


:check_python
rem Python dang chon phai chay duoc va >= 3.11; neu .venv hong (copy tu may khac) thi xoa de tao lai.
"%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 exit /b 0
if defined IS_PORTABLE (
    echo ***** Python portable khong chay duoc hoac thap hon 3.11. *****
    set "PYTHON="
    exit /b 0
)
echo ***** .venv khong dung duoc tren may nay, dang tao lai... *****
rmdir /s /q "%PROJECT_DIR%\.venv" >nul 2>&1
set "PYTHON="
exit /b 0


:create_venv
rem Uu tien 3.12/3.11/3.13 (co du wheel), roi ban moi nhat: py launcher, python3, python.
set "BASE_PYTHON="
for %%C in ("py -3.12" "py -3.11" "py -3.13" "py -3" "python3" "python") do if not defined BASE_PYTHON call :try_python %%~C
if not defined BASE_PYTHON goto :no_python
echo ***** Tao moi truong ao .venv bang: %BASE_PYTHON% *****
call %BASE_PYTHON% -m venv "%PROJECT_DIR%\.venv"
if errorlevel 1 goto :venv_failed
set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
exit /b 0

:try_python
rem %* la lenh ung vien, vi du: py -3.12
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "BASE_PYTHON=%*"
exit /b 0

:no_python
echo ***** Khong tim thay Python 3.11 tro len. *****
echo ***** Cai Python tu https://www.python.org/downloads/ - tick "Add python.exe to PATH" - roi chay lai. *****
exit /b 1

:venv_failed
echo ***** Khong tao duoc .venv bang %BASE_PYTHON% *****
exit /b 1


:find_portable_ffmpeg
rem FFmpeg di kem ban portable; chay tu ma nguon thi moviepy dung ban imageio-ffmpeg tu tai.
for /d %%D in ("%PORTABLE_DIR%\lib\ffmpeg\*") do call :pick_ffmpeg "%%~fD"
exit /b 0

:pick_ffmpeg
if exist "%~1\ffmpeg.exe" set "FFMPEG_BINARY=%~1\ffmpeg.exe"
if exist "%~1\bin\ffmpeg.exe" set "FFMPEG_BINARY=%~1\bin\ffmpeg.exe"
exit /b 0


:install_requirements
echo ***** Cai/cap nhat thu vien Python theo requirements.txt - lan dau co the mat vai phut... *****
"%PYTHON%" -m ensurepip --upgrade >nul 2>&1
"%PYTHON%" -m pip install -r "%PROJECT_DIR%\requirements.txt"
if errorlevel 1 goto :install_failed
copy /y "%PROJECT_DIR%\requirements.txt" "%REQUIREMENTS_STAMP%" >nul
echo ***** Da cai xong thu vien *****
exit /b 0

:install_failed
echo ***** Cai thu vien bi loi. Kiem tra mang/proxy roi chay lai update.bat *****
exit /b 1


:sync_portable_launchers
rem Cac file o thu muc ngoai chi goi file cung ten trong ma nguon; cap nhat khi ban trong portable\ doi.
for %%F in ("%PROJECT_DIR%\portable\*") do call :sync_one "%%~fF" "%PORTABLE_DIR%\%%~nxF"
exit /b 0

:sync_one
fc /b "%~1" "%~2" >nul 2>&1
if errorlevel 1 copy /y "%~1" "%~2" >nul
exit /b 0
