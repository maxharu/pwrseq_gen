"""
Power Sequence Generator - Windows EXE 打包腳本
使用 PyInstaller 將 GUI 打包成 .exe（--onefile 或 --onedir）
"""
import os
import subprocess
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
MAIN_SCRIPT = os.path.join(SRC_DIR, "main.py")
OUTPUT_NAME = "PowerSeqGen"
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
BUILD_ONEDIR_DIR = os.path.join(PROJECT_ROOT, "build-onedir")
# excel_export._TEMPLATE_CANDIDATES 的第一個「存在」的候選
EXCEL_TEMPLATE = "powerseq_nodes_template.xlsm"


def get_customtkinter_path() -> str:
    """取得 customtkinter 套件安裝路徑"""
    import customtkinter

    return os.path.dirname(customtkinter.__file__)


def build_command(*, onefile: bool) -> list[str]:
    """組出 PyInstaller 指令。獨立成純函式以便測試打包內容（tests/test_packaging.py）。"""
    ctk_path = get_customtkinter_path()
    reference_dir = os.path.join(SRC_DIR, "reference")
    scripts_dir = os.path.join(PROJECT_ROOT, "scripts")
    templates_dir = os.path.join(PROJECT_ROOT, "templates")
    workpath = BUILD_DIR if onefile else BUILD_ONEDIR_DIR

    return [
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
        # Excel 匯出需要的資源。templates/ 含未追蹤的客戶檔案，只能逐一指名，不可整包帶入。
        "--add-data",
        f"{os.path.join(templates_dir, EXCEL_TEMPLATE)}{os.pathsep}templates",
        "--add-data",
        f"{os.path.join(templates_dir, 'vba', 'vbaProject.bin')}{os.pathsep}templates/vba",
        # excel_export._finalize_xlsm 在執行期 import 這兩支，打包後要能解析
        "--paths",
        scripts_dir,
        "--hidden-import",
        "embed_excel_vba",
        "--hidden-import",
        "inject_vba_zip",
        "--hidden-import",
        "core.app_expiry",
        "--hidden-import",
        "timing.timing_scenario_io",
        MAIN_SCRIPT,
    ]


def run_build(*, onefile: bool) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Please install PyInstaller: pip install -r requirements-build.txt")
        return 1

    cmd = build_command(onefile=onefile)

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
