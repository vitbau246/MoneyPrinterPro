@echo off
setlocal
rem Chi mo WebUI (start.bat mo them bot Telegram).
call "%~dp0scripts\env.bat" || goto :fail
cd /d "%PROJECT_DIR%"

rem set HF_ENDPOINT=https://hf-mirror.com

if not defined MPT_WEBUI_HOST set "MPT_WEBUI_HOST=127.0.0.1"
if not defined MPT_WEBUI_PORT set "MPT_WEBUI_PORT=8501"

set "SELECTED_WEBUI_PORT="
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$hostAddress=$null; foreach ($address in [Net.Dns]::GetHostAddresses($env:MPT_WEBUI_HOST)) { if ($address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) { $hostAddress=$address; break } }; if ($null -eq $hostAddress) { exit 1 }; $preferred=[int]$env:MPT_WEBUI_PORT; $candidates=New-Object System.Collections.Generic.List[int]; $candidates.Add($preferred); foreach ($candidate in 8502..8599) { if ($candidate -ne $preferred) { $candidates.Add($candidate) } }; foreach ($port in $candidates) { $socket=[Net.Sockets.Socket]::new([Net.Sockets.AddressFamily]::InterNetwork,[Net.Sockets.SocketType]::Stream,[Net.Sockets.ProtocolType]::Tcp); try { $socket.Bind([Net.IPEndPoint]::new($hostAddress,$port)); $socket.Close(); Write-Output $port; exit 0 } catch { try { $socket.Close() } catch {} } }; exit 1"') do set "SELECTED_WEBUI_PORT=%%P"

if not defined SELECTED_WEBUI_PORT (
    echo ***** No available WebUI port found in 8501-8599 for %MPT_WEBUI_HOST%. *****
    echo ***** If Windows reports WinError 10013, check reserved ports: netsh interface ipv4 show excludedportrange protocol=tcp *****
    goto :fail
)

if not "%SELECTED_WEBUI_PORT%"=="%MPT_WEBUI_PORT%" (
    echo ***** Port %MPT_WEBUI_PORT% is unavailable, using %SELECTED_WEBUI_PORT% instead. *****
)
set "MPT_WEBUI_PORT=%SELECTED_WEBUI_PORT%"

echo ***** WebUI address: http://%MPT_WEBUI_HOST%:%MPT_WEBUI_PORT% *****
"%PYTHON%" -m streamlit run "%PROJECT_DIR%\webui\Main.py" --server.address=%MPT_WEBUI_HOST% --server.port=%MPT_WEBUI_PORT% --browser.serverAddress=%MPT_WEBUI_HOST% --browser.gatherUsageStats=False --client.toolbarMode=minimal --logger.hideWelcomeMessage=True --server.showEmailPrompt=False --server.enableCORS=True
exit /b %errorlevel%

:fail
pause
exit /b 1
