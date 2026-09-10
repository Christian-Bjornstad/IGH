@echo off
setlocal
cd /d "%~dp0"
echo Denne filen heter na INSTALL_IGH_MERGE.cmd.
call "%~dp0INSTALL_IGH_MERGE.cmd"
exit /b %errorlevel%
