@echo off
chcp 65001 >nul 2>&1
title Git Push - pwrseq_gen

cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 找不到 Git，請先安裝 Git
    pause
    exit /b 1
)

echo ============================================
echo   pwrseq_gen - Git Push
echo ============================================
echo.

git status --short
echo.

set /p MSG="請輸入 commit 訊息 (直接按 Enter 使用預設): "
if "%MSG%"=="" set MSG=Update %date% %time:~0,5%

echo.
echo [1/3] 加入所有變更...
git add .

echo [2/3] 建立 commit...
git commit -m "%MSG%"
if errorlevel 1 (
    echo.
    echo [INFO] 沒有需要 commit 的變更
    pause
    exit /b 0
)

echo [3/3] 推送到 GitHub...
git push origin main
if errorlevel 1 (
    echo.
    echo [ERROR] 推送失敗，請檢查網路連線或 GitHub 認證
    pause
    exit /b 1
)

echo.
echo ============================================
echo   推送完成！
echo   https://github.com/maxharu/pwrseq_gen
echo ============================================
echo.
pause
