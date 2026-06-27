"""Power Sequence GUI — design tokens, theme colors, and shared helpers."""
import os
import tkinter as tk

import customtkinter as ctk

from version import APP_NAME, APP_AUTHOR, APP_VERSION, APP_COPYRIGHT_YEAR

# 關閉自動 DPI 縮放，避免縮放時 dropdown 出現 TclError。
ctk.deactivate_automatic_dpi_awareness()
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ============================================================
# Design tokens
# ============================================================

SEQ_TYPE_LABELS = {"output": "Output", "input": "Input"}
DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"

# spacing
S_XS, S_SM, S_MD, S_LG = 2, 4, 8, 16



# About dialog only — change here without affecting the rest of the GUI
ABOUT_FONT_TITLE = ("", 16, "bold")
ABOUT_FONT_VERSION = ("", 14, "bold")
ABOUT_FONT_BODY = ("", 14)

# fonts
FONT_TITLE = ("", 14, "bold")
FONT_SECTION = ("", 12, "bold")
FONT_BODY = ("", 12)
FONT_CHIP = ("", 12, "bold")
FONT_HINT = ("", 12)
FONT_MONO = ("Consolas", 12)

# Hi / Lo / Force 色彩語意（與 Draw.io 輸出可同步）
COND_THEME = {
    "hi": {
        "name": "Hi Cond",
        "short": "Hi",
        "border": ("#2ea043", "#3fb950"),
        "text":   ("#1a7f37", "#3fb950"),
    },
    "lo": {
        "name": "Lo Cond",
        "short": "Lo",
        "border": ("#cf222e", "#ff7b72"),
        "text":   ("#cf222e", "#ff7b72"),
    },
    "force": {
        "name": "Force Cond",
        "short": "Force",
        "border": ("#9a6700", "#e3b341"),
        "text":   ("#9a6700", "#e3b341"),
    },
}


def _resolve_ctk_color(fg_color, appearance: str | None = None) -> str:
    """CTk fg_color（含 tuple / transparent）→ tk 可用的單色字串。"""
    if fg_color in (None, "transparent"):
        return ""
    if isinstance(fg_color, (list, tuple)):
        mode = appearance or ctk.get_appearance_mode()
        return fg_color[1] if mode == "Dark" else fg_color[0]
    return str(fg_color)


def _resolve_canvas_bg(widget: tk.Misc) -> str:
    """沿 widget 樹向上找非 transparent 的 fg_color，供 tk.Canvas bg 使用。"""
    w: tk.Misc | None = widget
    while w is not None:
        try:
            color = _resolve_ctk_color(w.cget("fg_color"))
        except Exception:
            color = ""
        if color:
            return color
        w = w.master
    return "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#f0f0f0"


def _make_hscroll_row(parent, *, bg_color: str = "", row_height: int = 34) -> ctk.CTkFrame:
    """單列橫向捲動容器；回傳 inner frame，子元件以 pack(side=left) 放入。"""
    shell = ctk.CTkFrame(parent, fg_color="transparent")
    shell.pack(fill="x", padx=S_SM, pady=S_XS)
    shell.grid_columnconfigure(0, weight=1)

    canvas = tk.Canvas(
        shell, height=row_height, highlightthickness=0, borderwidth=0,
        bg=bg_color or _resolve_ctk_color(parent.cget("fg_color")),
    )
    canvas.grid(row=0, column=0, sticky="ew")

    hbar = ctk.CTkScrollbar(shell, orientation="horizontal", command=canvas.xview)
    inner = ctk.CTkFrame(canvas, fg_color="transparent")
    win = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _sync_scroll(_evt=None):
        try:
            inner.update_idletasks()
            req_w = inner.winfo_reqwidth()
            req_h = max(row_height, inner.winfo_reqheight())
            canvas.configure(scrollregion=(0, 0, req_w, req_h), height=req_h)
            canvas.itemconfigure(win, width=req_w)
            viewport = canvas.winfo_width()
            if req_w > viewport and viewport > 0:
                canvas.configure(xscrollcommand=hbar.set)
                if not hbar.winfo_ismapped():
                    hbar.grid(row=1, column=0, sticky="ew", pady=(2, 0))
            else:
                hbar.grid_remove()
                canvas.configure(xscrollcommand=lambda *_a: None)
                canvas.xview_moveto(0)
        except Exception:
            pass

    def _on_shift_wheel(evt):
        try:
            canvas.xview_scroll(int(-1 * (evt.delta / 120)), "units")
            return "break"
        except Exception:
            pass

    inner.bind("<Configure>", _sync_scroll, add="+")
    shell.bind("<Configure>", _sync_scroll, add="+")
    for w in (canvas, inner):
        w.bind("<Shift-MouseWheel>", _on_shift_wheel, add="+")
    shell.after_idle(_sync_scroll)
    return inner

TYPE_THEME = {
    "output": {"pill_bg": ("#dbeafe", "#1e3a8a"), "pill_fg": ("#1e3a8a", "#dbeafe")},
    "input":  {"pill_bg": ("#fae8ff", "#581c87"), "pill_fg": ("#581c87", "#fae8ff")},
}

USE_LABELS = {"self": "Node", "hi": "Hi Cond", "lo": "Lo Cond", "force": "Force Cond"}
USE_REVERSE = {v: k for k, v in USE_LABELS.items()}

INPUT_WAVE_MODES = [
    ("Low (0)", "constant_0"),
    ("High (1)", "constant_1"),
    ("Custom wave", "custom"),
    ("Signal cond.", "depends"),
]
INPUT_WAVE_MODE_BY_LABEL = {label: val for label, val in INPUT_WAVE_MODES}
INPUT_WAVE_LABEL_BY_MODE = {val: label for label, val in INPUT_WAVE_MODES}

UNDO_LIMIT = 50


# ============================================================
# Helpers
# ============================================================

def _safe_int(s: str, default: int) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default


def make_chip(parent, text: str, *, fg=None, bg=None, font=FONT_CHIP) -> ctk.CTkLabel:
    if bg is None:
        bg = ("gray82", "gray28")
    if fg is None:
        fg = ("gray20", "gray85")
    return ctk.CTkLabel(
        parent, text=text, font=font,
        fg_color=bg, text_color=fg, corner_radius=6,
    )


def make_pill(parent, text: str, seq_type: str) -> ctk.CTkLabel:
    th = TYPE_THEME.get(seq_type, TYPE_THEME["output"])
    return ctk.CTkLabel(
        parent, text=text, font=FONT_CHIP,
        fg_color=th["pill_bg"], text_color=th["pill_fg"], corner_radius=8,
    )

# --- Preview / Schemdraw constants ---
PREVIEW_LANGS = ("Verilog", "C", "Schemdraw")
PREVIEW_FONT_FAMILY = FONT_MONO[0]
PREVIEW_FONT_SIZE_DEFAULT = FONT_MONO[1]
PREVIEW_FONT_SIZES = (8, 10, 12, 14, 16, 18, 20, 24)
PREVIEW_SCROLL_UNITS_Y = 4  # 滾輪垂直：每格 Tk units（約行數）
PREVIEW_SCROLL_UNITS_X = 4  # Shift+滾輪水平：每格 Tk units（約字元寬）
SCHEMDRAW_ZOOM_MIN = 0.1
SCHEMDRAW_ZOOM_MAX = 5.0
SCHEMDRAW_ZOOM_STEP = 1.2
SCHEMDRAW_ZOOM_DEBOUNCE_MS = 40


def _preview_font(size: int) -> tuple:
    return (PREVIEW_FONT_FAMILY, size)

_PWRSEQ_USER_DIR = os.path.join(os.path.expanduser("~"), ".pwrseq_gen")

__all__ = [
    "SEQ_TYPE_LABELS", "DEP_HIGH", "DEP_LOW",
    "S_XS", "S_SM", "S_MD", "S_LG",
    "APP_NAME", "APP_AUTHOR", "APP_VERSION", "APP_COPYRIGHT_YEAR",
    "ABOUT_FONT_TITLE", "ABOUT_FONT_VERSION", "ABOUT_FONT_BODY",
    "FONT_TITLE", "FONT_SECTION", "FONT_BODY", "FONT_CHIP", "FONT_HINT", "FONT_MONO",
    "COND_THEME", "TYPE_THEME", "USE_LABELS", "USE_REVERSE",
    "INPUT_WAVE_MODES", "INPUT_WAVE_MODE_BY_LABEL", "INPUT_WAVE_LABEL_BY_MODE",
    "UNDO_LIMIT",
    "PREVIEW_LANGS", "PREVIEW_FONT_FAMILY", "PREVIEW_FONT_SIZE_DEFAULT",
    "PREVIEW_FONT_SIZES", "PREVIEW_SCROLL_UNITS_Y", "PREVIEW_SCROLL_UNITS_X",
    "SCHEMDRAW_ZOOM_MIN", "SCHEMDRAW_ZOOM_MAX", "SCHEMDRAW_ZOOM_STEP",
    "SCHEMDRAW_ZOOM_DEBOUNCE_MS",
    "_resolve_ctk_color", "_resolve_canvas_bg", "_make_hscroll_row",
    "_safe_int", "make_chip", "make_pill", "_preview_font", "_PWRSEQ_USER_DIR",
]
