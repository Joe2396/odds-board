@echo off
setlocal
cd /d "%~dp0\..\.."

echo ==================================================
echo PROPS PART 6 OF 6 - WILLIAM HILL
echo Started: %date% %time%
echo ==================================================
echo.

echo [1/8] William Hill main props...
python scripts\Football\fetch_williamhill_worldcup_props.py
if errorlevel 1 (
    echo FAILED: William Hill main props.
    exit /b 1
)

echo.
echo [2/8] William Hill player shot-line normalization...
python scripts\Football\fix_williamhill_player_shot_lines.py
if errorlevel 1 (
    echo FAILED: William Hill shot-line normalization.
    exit /b 1
)

echo.
echo [3/8] William Hill embedded player shots...
python scripts\Football\fix_williamhill_embedded_player_shots.py
if errorlevel 1 (
    echo FAILED: William Hill embedded player shots.
    exit /b 1
)

echo.
echo [4/8] William Hill player market-key normalization...
python scripts\Football\fix_williamhill_player_market_keys.py
if errorlevel 1 (
    echo FAILED: William Hill player market-key normalization.
    exit /b 1
)

echo.
echo [5/8] William Hill match and team stats...
python scripts\Football\fetch_williamhill_worldcup_match_stats.py
if errorlevel 1 (
    echo FAILED: William Hill match/team stats.
    exit /b 1
)

echo.
echo [6/8] Merging William Hill match and team stats...
python scripts\Football\merge_williamhill_match_stats.py
if errorlevel 1 (
    echo FAILED: William Hill match/team stats merge.
    exit /b 1
)

echo.
echo [7/8] William Hill cards and corners...
python scripts\Football\fetch_williamhill_worldcup_cards_corners.py
if errorlevel 1 (
    echo FAILED: William Hill cards/corners.
    exit /b 1
)

echo.
echo [8/8] Merging William Hill cards and corners...
python scripts\Football\merge_williamhill_cards_corners.py
if errorlevel 1 (
    echo FAILED: William Hill cards/corners merge.
    exit /b 1
)

echo.
echo PROPS PART 6 COMPLETED: %date% %time%
exit /b 0
