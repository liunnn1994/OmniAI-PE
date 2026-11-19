@echo off
title OmniAI PE Startup
echo Initializing Windows PE...
wpeinit
if errorlevel 1 echo Windows PE initialization returned %errorlevel%.
set "policy=%ProgramFiles%\OmniAI Startup\policymanager.dll"
if exist "%policy%" if not exist "%SystemRoot%\System32\policymanager.dll" copy /b /y "%policy%" "%SystemRoot%\System32\policymanager.dll" >nul
echo Registering device dependencies...
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "%SystemRoot%\System32\OmniAI-Devices.ps1" >"%SystemRoot%\Temp\omniai-devices.log" 2>&1
if errorlevel 1 echo Device initialization reported errors. See %SystemRoot%\Temp\omniai-devices.log.
echo Starting desktop and HotPE tools...
call "%SystemRoot%\System32\OmniAI-Start.cmd"
echo OmniAI PE startup finished.
