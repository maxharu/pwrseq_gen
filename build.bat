@echo off
REM Power Sequence Generator - Windows EXE 打包
REM 請先執行: pip install -r requirements.txt
REM            pip install -r requirements-build.txt

echo ========================================
echo Power Sequence Generator - 打包 EXE
echo ========================================
echo.

REM 檢查必要套件
python -c "import customtkinter" 2>nul || (
    echo 錯誤: 請先安裝 requirements.txt
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)
python -c "import PyInstaller" 2>nul || (
    echo 錯誤: 請先安裝 requirements-build.txt
    echo   pip install -r requirements-build.txt
    pause
    exit /b 1
)

echo 開始打包...
python build.py

echo.
pause
