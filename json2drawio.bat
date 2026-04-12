@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

if "%~1"=="" (
    echo Usage: json2drawio.bat [--optimize] ^<input.json^> [-o output.xml]
    echo.
    echo   input.json    Power Sequence JSON config (supports wildcards)
    echo   -o output.xml Optional output path (default: same name as input)
    echo   --optimize    Enable layout optimization
    echo.
    echo Examples:
    echo   json2drawio.bat output\test.json
    echo   json2drawio.bat output\test.json -o result.xml
    echo   json2drawio.bat output\*.json --optimize
    pause
    exit /b 1
)

python src\json2drawio.py %*
if errorlevel 1 pause
