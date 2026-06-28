@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo William Hill V12 local review site
echo ============================================================

python scripts\Football\build_williamhill_v12_review_site.py
if errorlevel 1 (
    echo.
    echo The review site could not be built.
    pause
    exit /b 1
)

start "" "http://localhost:8765"
echo.
echo Local site: http://localhost:8765
echo Press Ctrl+C in this window when finished.
echo.

python -m http.server 8765 --directory "football\debug\williamhill_v12_review_site"
endlocal
