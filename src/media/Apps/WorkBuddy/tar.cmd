@echo off
rem shortcut: supports WorkBuddy's bundled-runtime extraction only, remove when WinPE ships tar.
if /i not "%~1"=="-xf" exit /b 64
if /i not "%~3"=="-C" exit /b 64
if "%~2"=="" exit /b 64
if "%~4"=="" exit /b 64
"%SystemRoot%\System32\7z.exe" x -y "-o%~4" -- "%~2"
exit /b %errorlevel%
