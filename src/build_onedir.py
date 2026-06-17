"""
Power Sequence Generator - Windows EXE 打包腳本（--onedir）
輸出 dist/PowerSeqGen/ 資料夾，防毒誤判率通常低於單檔 exe。
"""
import sys

from build import run_build


def main():
    sys.exit(run_build(onefile=False))


if __name__ == "__main__":
    main()
