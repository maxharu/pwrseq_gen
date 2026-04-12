"""
Power Sequence Generator - Windows EXE 打包腳本
使用 PyInstaller 將 GUI 打包成可直接執行的 .exe
"""
import os
import subprocess
import sys

# 專案根目錄
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, "main.py")
OUTPUT_NAME = "PowerSeqGen"


def get_customtkinter_path() -> str:
    """取得 customtkinter 套件安裝路徑"""
    import customtkinter
    pkg_dir = os.path.dirname(customtkinter.__file__)
    return pkg_dir


def main():
    # 檢查 PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("Please install PyInstaller: pip install pyinstaller")
        sys.exit(1)

    ctk_path = get_customtkinter_path()
    # PyInstaller --add-data 格式：來源;目標（Windows 用分號）
    add_data = f"{ctk_path};customtkinter/"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",           # CustomTkinter 有 .json/.otf 等資料檔，需用 onedir
        "--windowed",         # GUI 程式不顯示 console
        "--name", OUTPUT_NAME,
        "--add-data", add_data,
        MAIN_SCRIPT,
    ]

    print("Running build command...")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode == 0:
        dist_dir = os.path.join(PROJECT_ROOT, "dist", OUTPUT_NAME)
        print()
        print("=" * 50)
        print("Build completed successfully!")
        print(f"Output: {dist_dir}\\{OUTPUT_NAME}.exe")
        print()
        print("Copy the entire dist\\PowerSeqGen folder to run on target PC.")
        print("=" * 50)
    else:
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
