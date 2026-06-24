@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."

set "DONE_FILE=%~1"
set "BRANCH_WARNINGS=0"

echo ========================================
echo Bwin fast branch started
echo ========================================
echo.

echo [Bwin 1/3] Moneylines...
python scripts\Football\fetch_bwin_worldcup_moneylines.py
if errorlevel 1 (
    echo WARNING: Bwin moneylines failed; previous good JSON will be retained.
    set "BRANCH_WARNINGS=1"
)

echo.
echo [Bwin 2/3] Ordinary and player props...
python scripts\Football\fetch_bwin_worldcup_props.py
if errorlevel 1 (
    echo WARNING: Bwin props failed; previous good JSON will be retained.
    set "BRANCH_WARNINGS=1"
)

echo.
echo [Bwin 3/3] Match and team shots stats...
python scripts\Football\fetch_bwin_worldcup_match_stats.py
if errorlevel 1 (
    echo WARNING: Bwin match stats did not produce a complete new dataset.
    echo Previous complete production JSON will be retained.
    set "BRANCH_WARNINGS=1"
)

echo.
echo ========================================
echo Bwin fast branch finished
echo Warnings: %BRANCH_WARNINGS%
echo ========================================

> "%DONE_FILE%" echo 0
exit /b 0
