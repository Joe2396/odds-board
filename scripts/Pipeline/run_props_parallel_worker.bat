@echo off
setlocal EnableExtensions

rem Force UTF-8 for every Python scraper whose output is redirected to log files.
rem Without this, Windows may use cp1252 and crash on Unicode symbols.
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

set "PART_SCRIPT=%~1"
set "LOG_FILE=%~2"
set "STATUS_FILE=%~3"

if not exist "%PART_SCRIPT%" (
    >"%LOG_FILE%" echo ERROR: Missing props part script: %PART_SCRIPT%
    >"%STATUS_FILE%" echo 9009
    exit /b 9009
)

call "%PART_SCRIPT%" >"%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"

>"%STATUS_FILE%" echo %RC%
exit /b %RC%
