@echo off
setlocal
set "app=%LOCALAPPDATA%\OmniAI-PE\PixPin"
robocopy "%~dp0Portable\PixPin" "%app%" /E /COPY:DT /R:0 /W:0 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto failed
if not exist "%app%\MFReadWrite.dll" (
    copy /Y "%~dp0MFReadWrite.dll" "%app%\MFReadWrite.dll" >nul
    if errorlevel 1 goto failed
)

rem Qt requires the Network List Manager class to be registered in WinPE.
set "nlm=HKLM\SOFTWARE\Classes\CLSID\{DCB00C01-570F-4A9B-8D69-199FDBA5723B}\InProcServer32"
reg query "%nlm%" /ve >nul 2>&1
if errorlevel 1 (
    reg add "%nlm%" /v ThreadingModel /t REG_SZ /d Both /f >nul
    if errorlevel 1 goto failed
    reg add "%nlm%" /ve /t REG_SZ /d "%SystemRoot%\System32\netprofm.dll" /f >nul
    if errorlevel 1 goto failed
)

start "" /d "%app%" "%app%\PixPin.exe"
if not errorlevel 1 exit /b 0

:failed
echo Failed to start PixPin.
pause
exit /b 1
