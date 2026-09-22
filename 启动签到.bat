@echo off
rem ===========================================================
rem  Weibo Super Sign-in - main entry
rem  Double-click this file. It will:
rem    1. find Python, install it if missing
rem    2. check / install dependencies
rem    3. log in (first time) then sign in
rem  All user-facing messages are printed by Python (Chinese).
rem ===========================================================
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Weibo Super Sign-in
echo   Folder: %~dp0
echo ============================================================
echo.

set "PYEXE="
call :findpy

if not defined PYEXE (
    echo [1/3] Python not found on this computer. Installing Python 3.12 ...
    echo       It downloads about 25 MB from python.org, then installs silently.
    echo.
    call :installpy
    call :findpy
)

if not defined PYEXE (
    echo.
    echo [ERROR] Python could not be installed automatically.
    echo         Please install Python 3.8+ manually from
    echo         https://www.python.org/downloads/windows/
    echo         Tick "Add python.exe to PATH" during setup, then run this file again.
    echo.
    pause
    exit /b 1
)

echo [OK] Python found: %PYEXE%
echo.
echo [2/3] Checking dependencies ...
%PYEXE% "%~dp0setup_env.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency setup failed. Read the messages above.
    echo.
    pause
    exit /b 1
)

echo.
echo [3/3] Running sign-in ...
%PYEXE% "%~dp0weibo_signin.py" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo Finished. Everything is fine.
) else (
    echo Something went wrong ^(exit code %RC%^).
    echo Check the "logs" folder, and the alert file on your Desktop.
)
echo.
pause
exit /b %RC%

rem -----------------------------------------------------------
:findpy
if exist "%~dp0python\python.exe" ( set "PYEXE=%~dp0python\python.exe" & exit /b 0 )
py -3 -c "import sys" >nul 2>&1 && ( set "PYEXE=py -3" & exit /b 0 )
python -c "import sys" >nul 2>&1 && ( set "PYEXE=python" & exit /b 0 )
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ( set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & exit /b 0 )
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" ( set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & exit /b 0 )
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" ( set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe" & exit /b 0 )
if exist "C:\Python312\python.exe" ( set "PYEXE=C:\Python312\python.exe" & exit /b 0 )
if exist "C:\Python311\python.exe" ( set "PYEXE=C:\Python311\python.exe" & exit /b 0 )
exit /b 1

rem -----------------------------------------------------------
:installpy
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
set "PYINS=%TEMP%\python-3.12.10-amd64.exe"
if exist "%PYINS%" del /q "%PYINS%" >nul 2>&1
curl -L --fail --silent --show-error -o "%PYINS%" "%PYURL%"
if not exist "%PYINS%" (
    echo       curl failed, trying Invoke-WebRequest ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYINS%' } catch { exit 1 }"
)
if not exist "%PYINS%" (
    echo       Download failed. Check the network connection.
    exit /b 1
)
echo       Download OK. Installing silently, please wait ...
rem InstallAllUsers=0 -> installs under %LOCALAPPDATA%, no admin rights needed
"%PYINS%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
exit /b 0
