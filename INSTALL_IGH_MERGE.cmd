@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "IVANTI=C:\Program Files (x86)\Ivanti\Workspace Control\pwrgate.exe"
set "INSTALL_SCRIPT=%~dp0install_python_felles.py"

if not exist "%IVANTI%" (
  echo Ivanti Workspace Control ble ikke funnet. Kontakt teknisk stotte.
  pause
  exit /b 1
)

if not exist "%INSTALL_SCRIPT%" (
  echo Installasjonsskriptet ble ikke funnet:
  echo %INSTALL_SCRIPT%
  pause
  exit /b 1
)

rem Ren cmd: bygg Python-kommandoen i en variabel og kopier med clip.exe.
set "PAYLOAD=import runpy; runpy.run_path(r'%INSTALL_SCRIPT%', run_name='igh_merge_install_felles')['main']()"
<nul set /p "=%PAYLOAD%" | clip.exe
if errorlevel 1 (
  echo Installasjonskommandoen kunne ikke kopieres til utklippstavlen.
  pause
  exit /b 1
)

start "" "%IVANTI%" 15694
echo Python FELLES apnes. Lim inn kommandoen med Ctrl+V og trykk Enter.
pause
