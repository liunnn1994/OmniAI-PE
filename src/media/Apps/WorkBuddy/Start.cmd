@echo off
setlocal
rem The PE system volume cannot create WorkBuddy's managed-runtime junctions.
set "vendor=%~dp0resources\vendor"
set "CODEBUDDY_CODE_GIT_BASH_PATH=%vendor%\PortableGit\bin\bash.exe"
set "WORKBUDDY_EXTRA_PATHS=%vendor%\PortableGit\cmd;%vendor%\python"
set "PATH=%WORKBUDDY_EXTRA_PATHS%;%PATH%"
start "" /d "%~dp0." "%~dp0WorkBuddy.exe" --disable-direct-composition
