@echo off
set "PATH=%ProgramFiles%\7-Zip;%ProgramFiles%\Edgeless\plugin_ept;%ProgramFiles%\Python;%ProgramFiles%\NodeJS;%PATH%"
set "USERPROFILE=%SystemDrive%\Users\Default"
set "APPDATA=%USERPROFILE%\AppData\Roaming"
set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
if not exist "%USERPROFILE%\Desktop\" md "%USERPROFILE%\Desktop"
if not exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\" md "%APPDATA%\Microsoft\Windows\Start Menu\Programs"

"%SystemRoot%\System32\Pecmd.exe" LOAD "%SystemRoot%\OmniAI-Devices.ini"
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "%SystemRoot%\System32\OmniAI-Display.ps1"
"%SystemRoot%\System32\Pecmd.exe" LOAD "%ProgramFiles%\PETools\AutoDPI.WCS"
"%ProgramFiles%\PETools\vtoydump.exe" -m
for %%F in (7z.exe 7z.dll) do (
    if exist "%ProgramFiles%\7-Zip\%%F" if not exist "%SystemRoot%\System32\%%F" (
        copy /b "%ProgramFiles%\7-Zip\%%F" "%SystemRoot%\System32\%%F" >nul
    )
)
if exist "%SystemRoot%\explorer.exe" (
    reg import "%ProgramFiles%\PETools\PlainAppearance.reg"
    start "" "%ProgramFiles%\WinXShell\WinXShell.exe" -regist -daemon
    start "" "%ProgramFiles%\PETools\ShellFix\ShellF5.exe"
    start "" "%ProgramFiles%\PETools\ShellFix\ShellR32.exe"
)
for %%D in (C D E F G H I J K L M N O P Q R S T U V W Y Z) do (
    if exist "%%D:\OmniAIPE\OmniAIPE.INI" "%SystemRoot%\System32\Pecmd.exe" LOAD "%%D:\OmniAIPE\OmniAIPE.INI"
)
"%SystemRoot%\System32\Pecmd.exe" LOAD "%ProgramFiles%\PETools.ini"
start "" "%ProgramFiles%\WinXShell\WinXShell.exe" -winpe
if exist "%SystemRoot%\System32\drivers\mtpHelper.sys" (
    sc.exe create mtpHelper type= kernel start= demand error= ignore binPath= "System32\Drivers\mtpHelper.sys" >"%SystemRoot%\Temp\omniai-mtp.log" 2>&1
    start "" /b cmd.exe /d /c "sc.exe start mtpHelper >>%SystemRoot%\Temp\omniai-mtp.log 2>&1"
)
exit /b 0
