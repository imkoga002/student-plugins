@echo off
rem rk.cmd - ryukoku-writing project command for cmd.exe and PowerShell (.\rk.cmd setup). Unofficial. See rk
rem (POSIX) for why it runs the installed plugin's code, located through %USERPROFILE%\.ryukoku-writing\plugin-root.
rem Not tried on a Windows machine yet (README).
setlocal
set "RKH=%RK_STATE_HOME%"
if "%RKH%"=="" set "RKH=%USERPROFILE%\.ryukoku-writing"
set "RKP="
if exist "%RKH%\plugin-root" set /p RKP=<"%RKH%\plugin-root"
rem prefer the py launcher (python.org installs it); "python" can be the Microsoft Store stub
set "PY="
where py >nul 2>nul && set "PY=py -3"
if "%PY%"=="" set "PY=python"
if "%RKP%"=="" goto local
if not exist "%RKP%\scripts\rk\rk.py" goto local
%PY% -I -B "%RKP%\scripts\rk\rk.py" --project "%~dp0." %*
exit /b
:local
%PY% -I -B "%~dp0tools\rk\rk.py" --project "%~dp0." %*
exit /b
