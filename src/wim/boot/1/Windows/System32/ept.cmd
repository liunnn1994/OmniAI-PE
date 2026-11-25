@echo off
setlocal
set "PATH=%ProgramFiles%\Edgeless\plugin_ept;%PATH%"
call "%ProgramFiles%\Edgeless\plugin_ept\ept.cmd" %*
exit /b %errorlevel%
