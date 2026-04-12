@echo off
chcp 65001 >nul 2>&1
title Power Sequence Generator

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 找不到 Python，請先安裝 Python 3.8 以上版本
    pause
    exit /b 1
)

pip show customtkinter >nul 2>&1
if errorlevel 1 (
    echo 正在安裝相依套件...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] 套件安裝失敗，請手動執行: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

echo 啟動 Power Sequence Generator...
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] 程式異常結束 (exit code: %errorlevel%)
    pause
)
