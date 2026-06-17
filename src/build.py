"""
Power Sequence Generator - Windows EXE 打包腳本
使用 PyInstaller 將 GUI 打包成 .exe（--onefile 或 --onedir）
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
BUILD_ONEDIR_DIR = os.path.join(PROJECT_ROOT, "build-onedir")


def get_customtkinter_path() -> str:
    """取得 customtkinter 套件安裝路徑"""
    import customtkinter

    return os.path.dirname(customtkinter.__file__)


def run_build(*, onefile: bool) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Please install PyInstaller: pip install -r requirements-build.txt")
        return 1

    ctk_path = get_customtkinter_path()
    reference_dir = os.path.join(SRC_DIR, "reference")
    workpath = BUILD_DIR if onefile else BUILD_ONEDIR_DIR

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile" if onefile else "--onedir",
        "--windowed",
        "--distpath",
        DIST_DIR,
        "--workpath",
        workpath,
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

    mode = "onefile" if onefile else "onedir"
    print(f"Running {mode} build command...")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        return result.returncode

    if onefile:
        exe_path = os.path.join(DIST_DIR, f"{OUTPUT_NAME}.exe")
        deploy_hint = (
            "Single-file EXE — copy PowerSeqGen.exe to target PC to run.\n"
            "First launch may take a few seconds while files extract."
        )
    else:
        exe_path = os.path.join(DIST_DIR, OUTPUT_NAME, f"{OUTPUT_NAME}.exe")
        deploy_hint = (
            f"Folder deploy — copy the entire dist\\{OUTPUT_NAME}\\ folder to target PC.\n"
            f"Run {OUTPUT_NAME}.exe inside that folder."
        )

    print()
    print("=" * 50)
    print("Build completed successfully!")
    print(f"Output: {exe_path}")
    print()
    print(deploy_hint)
    print("=" * 50)
    return 0


def main():
    sys.exit(run_build(onefile=True))


if __name__ == "__main__":
    main()
