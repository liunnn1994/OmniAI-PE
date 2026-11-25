@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Open-LocalPlugin.ps1" "%~1"
exit /b %errorlevel%
