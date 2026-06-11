"""
Power Sequence Generator - Windows EXE 打包腳本
使用 PyInstaller 將 GUI 打包成單一 .exe（--onefile）
"""
import os
import subprocess
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
MAIN_SCRIPT = os.path.join(SRC_DIR, "main.py")
OUTPUT_NAME = "PowerSeqGen"
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")


def get_customtkinter_path() -> str:
    """取得 customtkinter 套件安裝路徑"""
    import customtkinter

    return os.path.dirname(customtkinter.__file__)


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Please install PyInstaller: pip install -r requirements-build.txt")
        sys.exit(1)

    ctk_path = get_customtkinter_path()
    reference_dir = os.path.join(SRC_DIR, "reference")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--distpath",
        DIST_DIR,
        "--workpath",
        BUILD_DIR,
        "--specpath",
        PROJECT_ROOT,
        "--name",
        OUTPUT_NAME,
        "--add-data",
        f"{ctk_path}{os.pathsep}customtkinter",
        "--add-data",
        f"{reference_dir}{os.pathsep}reference",
        "--hidden-import",
        "app_expiry",
        "--hidden-import",
        "wavedrom_scenario_io",
        MAIN_SCRIPT,
    ]

    print("Running build command...")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode == 0:
        exe_path = os.path.join(DIST_DIR, f"{OUTPUT_NAME}.exe")
        print()
        print("=" * 50)
        print("Build completed successfully!")
        print(f"Output: {exe_path}")
        print()
        print("Single-file EXE — copy PowerSeqGen.exe to target PC to run.")
        print("First launch may take a few seconds while files extract.")
        print("=" * 50)
    else:
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
