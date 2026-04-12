"""
Power Sequence Generator - 主程式進入點
以 main.py 啟動時先設定 Windows DPI 感知，避免視窗縮放時觸發 CustomTkinter 的 scaling 錯誤。
"""
import sys

if sys.platform == "win32":
    try:
        import ctypes
        # 與以 gui.py 直接啟動時之 DPI 行為一致，避免縮放時 TclError (dropdownmenu)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from gui import run_gui

if __name__ == "__main__":
    run_gui()
