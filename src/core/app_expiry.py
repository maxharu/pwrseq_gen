"""Application expiry — block GUI use after the trial end date."""
from __future__ import annotations

from datetime import date

import tkinter as tk
from tkinter import messagebox

# Last valid calendar day (inclusive). Expired from the next day onward.
EXPIRY_LAST_VALID = date(2027, 6, 30)


def is_expired(today: date | None = None) -> bool:
    today = today or date.today()
    return today > EXPIRY_LAST_VALID


def ensure_not_expired() -> bool:
    """Show a dialog and return False when the app has expired."""
    if not is_expired():
        return True
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror(
            "Trial Expired",
            "Power Sequence Generator trial ended on 2027/6/30. The application cannot be used.",
            parent=root,
        )
    finally:
        root.destroy()
    return False
