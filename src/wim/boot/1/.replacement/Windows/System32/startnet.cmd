@echo off
for /f "tokens=2 delims=:" %%P in ('chcp') do set "startup_cp=%%P"
chcp 65001 >nul
title OmniAI PE 启动
echo 正在初始化 Windows PE……
wpeinit
if errorlevel 1 echo Windows PE 初始化返回代码 %errorlevel%。
set "policy=%ProgramFiles%\OmniAI Startup\policymanager.dll"
if exist "%policy%" if not exist "%SystemRoot%\System32\policymanager.dll" copy /b /y "%policy%" "%SystemRoot%\System32\policymanager.dll" >nul
echo 正在注册设备所需组件……
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "%SystemRoot%\System32\OmniAI-Devices.ps1" >"%SystemRoot%\Temp\omniai-devices.log" 2>&1
if errorlevel 1 echo 设备初始化出现错误。日志：%SystemRoot%\Temp\omniai-devices.log
echo 正在启动桌面和工具……
call "%SystemRoot%\System32\OmniAI-Start.cmd"
echo OmniAI PE 启动完成。
if defined startup_cp chcp %startup_cp% >nul

rem Keep the WinPE shell process alive and hide its console.
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "%SystemRoot%\System32\OmniAI-HideStartup.ps1"
