@echo off
setlocal
set "GPUI_DISABLE_DIRECT_COMPOSITION=1"
start "" /d "%~dp0." "%~dp0Zed.exe" %*
