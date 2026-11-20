@echo off
setlocal
for /f "tokens=2 delims=:" %%P in ('chcp') do set "startup_cp=%%P"
set "install=%SystemDrive%\OmniAI\UURemote"
set "bin=%install%\GameViewer\bin"
set "ready=%install%\.ready"

md "%install%.lock" 2>nul
if errorlevel 1 (
    if exist "%install%.lock\" exit /b 0
    goto failed
)
if exist "%ready%" if exist "%bin%\GameViewer.exe" goto prepared
chcp 65001 >nul
echo 正在准备 UU 远程，请稍候……
if defined startup_cp chcp %startup_cp% >nul
start "" /wait "%~dp0UUSetup.exe" /S /D=%install%
if errorlevel 1 goto install_failed
if not exist "%bin%\GameViewer.exe" goto install_failed
type nul > "%ready%" || goto install_failed

:prepared
rd "%install%.lock" 2>nul
start "" /d "%bin%" "%bin%\GameViewer.exe"
exit /b %errorlevel%

:install_failed
rd "%install%.lock" 2>nul
:failed
chcp 65001 >nul
echo UU 远程启动失败。请检查 PE 内存盘剩余空间。
if defined startup_cp chcp %startup_cp% >nul
pause
exit /b 1
