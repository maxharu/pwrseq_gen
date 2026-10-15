@echo off
REM 本地 CI。push / 開 PR 前必須全綠。
REM .github/workflows/ci.yml 直接呼叫這支，所以本地與 CI 不可能跑到不同指令。
REM 黃金輸出比對在 tests/test_golden_exports.py 裡，不需要獨立步驟。
setlocal

echo === ruff ===
python -m ruff check .
if errorlevel 1 goto fail

echo.
echo === pytest ===
python -m pytest -q
if errorlevel 1 goto fail

echo.
echo CI PASSED
exit /b 0

:fail
echo.
echo CI FAILED
exit /b 1
