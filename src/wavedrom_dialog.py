"""
WaveDrom export dialog: per-input hi/lo settings for simulation only.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

from config_models import PowerSeqConfig
from wavedrom_scenario_io import (
    load_scenario_file,
    merge_scenario_for_config,
    resolve_scenario,
    save_scenario_file,
)
from wavedrom_sim import DEP_HIGH, DEP_LOW, InputWaveSpec, WaveDromScenario, _norm_hscale

HI_LO_MODES = [
    ("Low (0)", "constant_0"),
    ("High (1)", "constant_1"),
    ("Custom wave", "custom"),
    ("Signal cond.", "depends"),
]

# CTkFrame default height is 200; nested opt frames must be explicit.
_ROW_H = 28
_CTRL_H = 26
_TABLE_COLS = [
    ("Input", 120),
    ("Hi", 110),
    ("Hi opt.", 100),
    ("Lo", 110),
    ("Lo opt.", 100),
]


def _release_modal_grab(window: tk.Misc) -> None:
    try:
        window.grab_release()
    except tk.TclError:
        pass


class _ModalToplevelMixin:
    """Recover Toplevel visibility after Win+D (Show Desktop) on Windows."""

    _default_geom: str = "640x400"

    def _close_modal(self) -> None:
        if getattr(self, "_closing", False):
            return
        self._closing = True
        _release_modal_grab(self)
        on_closed = getattr(self, "_on_closed", None)
        if on_closed:
            on_closed()
        self.destroy()

    def _place_over_master(self) -> None:
        """Center on parent so the dialog is not left off-screen after Win+D."""
        master = self.master
        if master is None:
            return
        try:
            if not master.winfo_exists():
                return
        except tk.TclError:
            return
        self.update_idletasks()
        master.update_idletasks()
        try:
            parts = self._default_geom.split("x", 1)
            w, h = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            w, h = 640, 400
        try:
            mw = max(master.winfo_width(), 100)
            mh = max(master.winfo_height(), 100)
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
        except tk.TclError:
            mx, my, mw, mh = 0, 0, w, h
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, min(mx + (mw - w) // 2, max(0, sw - w)))
        y = max(0, min(my + (mh - h) // 2, max(0, sh - h)))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def bring_to_front(self, *, use_grab: bool = False) -> bool:
        try:
            if not self.winfo_exists():
                return False
            _release_modal_grab(self)
            self.deiconify()
            if str(self.state()) == "iconic":
                self.state("normal")
            self._place_over_master()
            master = self.master
            if master is not None:
                try:
                    self.transient(master)
                    self.lift(master)
                except tk.TclError:
                    self.lift()
            else:
                self.lift()
            self.attributes("-topmost", True)
            self.update_idletasks()
            self.focus_force()
            self.after(80, lambda: self.attributes("-topmost", False))
            if use_grab:
                try:
                    self.grab_set()
                except tk.TclError:
                    pass
            return True
        except tk.TclError:
            return False


class InputCondEditorDialog(_ModalToplevelMixin, ctk.CTkToplevel):
    def __init__(
        self,
        master,
        config: PowerSeqConfig,
        input_name: str,
        kind: str,
        initial_groups: list[list[str]],
        initial_inv_groups: list[list[bool]],
        initial_use_groups: list[list[str]],
        on_save: Callable[[list, list, list], None],
    ):
        super().__init__(master)
        self._default_geom = "520x360"
        self.title(f"{input_name} — {kind.upper()} signal condition")
        self.geometry(self._default_geom)
        self.minsize(440, 280)
        self.transient(master)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.after(50, self._place_over_master)

        from gui import CondSectionFrame

        name_to_rail = {r.name: r for r in config.rails}

        def dep_options() -> list[str]:
            opts = ["High", "Low"]
            for r in config.rails:
                opts.append(r.name)
            return opts

        def is_pseqcell(name: str) -> bool:
            if name in (DEP_HIGH, DEP_LOW):
                return False
            r = name_to_rail.get(name)
            return bool(r and r.has_pseqcell)

        hdr = ctk.CTkLabel(
            self,
            text="AND within group, OR across groups. Pick input/output signals "
            "(output: Node / Hi cond / Lo cond).",
            font=("", 11),
            text_color="gray",
            wraplength=480,
            justify="left",
        )
        hdr.pack(anchor="w", padx=12, pady=(12, 8))

        self._section = CondSectionFrame(
            self,
            kind=kind,
            get_dep_options=dep_options,
            is_pseqcell_for=is_pseqcell,
            initial_groups=initial_groups or [[]],
            initial_inv_groups=initial_inv_groups,
            initial_use_groups=initial_use_groups,
            initial_inv_flat={},
            initial_use_flat={},
        )
        self._section.pack(fill="both", expand=True, padx=12, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(btn_row, text="Cancel", width=90, command=self._close_modal).pack(
            side="right", padx=(8, 0)
        )
        ctk.CTkButton(
            btn_row, text="OK", width=90,
            command=lambda: self._save(on_save),
        ).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._close_modal)
        self.bind("<Escape>", lambda _e: self._close_modal())

    def _save(self, on_save: Callable):
        on_save(
            self._section.get_groups(),
            self._section.get_inv_groups(),
            self._section.get_use_groups(),
        )
        self._close_modal()


class WaveDromExportDialog(_ModalToplevelMixin, ctk.CTkToplevel):
    def __init__(
        self,
        master,
        config: PowerSeqConfig,
        on_export: Callable[[WaveDromScenario], None],
        scenario_path_hint: Optional[str] = None,
        project_json_path: Optional[str] = None,
        on_closed: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self._on_closed = on_closed
        self._closing = False
        self.config = config
        self.on_export = on_export
        self._scenario_path_hint = scenario_path_hint
        self._last_save_path = (
            scenario_path_hint
            if scenario_path_hint and scenario_path_hint.lower().endswith(".json")
            else None
        )
        self._rows: dict[str, dict] = {}
        self._name_to_rail = {r.name: r for r in config.rails}

        self.title("Export WaveDrom")
        self._default_geom = "820x480"
        self.geometry(self._default_geom)
        self.minsize(680, 320)
        self.transient(master)
        # No grab_set: Win+D can hide the window while grab blocks the whole app.

        self._saved = resolve_scenario(config, project_json_path)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close_modal)
        self.bind("<Escape>", lambda _e: self._close_modal())
        self.after(80, lambda: self.bring_to_front())

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            hdr,
            text="Input hi/lo is for WaveDrom simulation only (not rail depends_on_*). "
            "Export: binary 0/1 waves, compact layout (narrow skin). "
            "Hi default: Signal cond.; Lo: Low (0). constant_1 = High in scenario JSON.",
            font=("", 11),
            text_color="gray",
            wraplength=760,
            justify="left",
        ).pack(anchor="w")

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(opts, text="Steps:").pack(side="left", padx=(0, 8))
        self._steps_var = tk.StringVar(value=str(self._saved.steps))
        ctk.CTkEntry(opts, textvariable=self._steps_var, width=80, height=_CTRL_H).pack(
            side="left"
        )
        ctk.CTkLabel(opts, text="hscale:").pack(side="left", padx=(16, 8))
        self._hscale_var = tk.StringVar(value=str(self._saved.hscale))
        ctk.CTkEntry(opts, textvariable=self._hscale_var, width=48, height=_CTRL_H).pack(
            side="left"
        )
        ctk.CTkLabel(
            opts,
            text="(WaveDrom horizontal scale per step; default 1)",
            font=("", 11),
            text_color="gray",
        ).pack(side="left", padx=(8, 0))

        self._pack_table_header()

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self._table = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._table.pack(fill="x", anchor="n")
        for col, (_, w) in enumerate(_TABLE_COLS):
            self._table.grid_columnconfigure(col, minsize=w)

        inputs = [r for r in self.config.rails if r.seq_type == "input"]
        if not inputs:
            ctk.CTkLabel(self._table, text="(no input nodes)").grid(
                row=0, column=0, columnspan=len(_TABLE_COLS), sticky="w", pady=2
            )
        for row_idx, r in enumerate(inputs):
            self._add_input_row(r.name, row_idx)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(btn_row, text="Close", width=90, command=self._close_modal).pack(
            side="right", padx=(8, 0)
        )
        ctk.CTkButton(
            btn_row, text="Export WaveDrom...", width=130, command=self._do_export,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_row, text="Save As...", width=90, command=self._do_save_as,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_row, text="Save", width=70, command=self._do_save,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_row, text="Load", width=70, command=self._do_load,
        ).pack(side="right", padx=(8, 0))

    def _pack_table_header(self):
        hdr_row = ctk.CTkFrame(self, fg_color="transparent")
        hdr_row.pack(fill="x", padx=12, pady=(0, 2))
        for col, (_, w) in enumerate(_TABLE_COLS):
            hdr_row.grid_columnconfigure(col, minsize=w)
        for col, (text, w) in enumerate(_TABLE_COLS):
            ctk.CTkLabel(
                hdr_row, text=text, font=("", 11, "bold"), width=w, anchor="w",
            ).grid(row=0, column=col, padx=2, sticky="w")

    def _opt_slot(self, master) -> ctk.CTkFrame:
        slot = ctk.CTkFrame(master, fg_color="transparent", width=100, height=_ROW_H)
        slot.pack_propagate(False)
        return slot

    def _add_input_row(self, name: str, row_idx: int):
        spec = self._saved.inputs.get(name) or InputWaveSpec()
        pad = {"padx": 2, "pady": 1}

        ctk.CTkLabel(
            self._table, text=name, width=_TABLE_COLS[0][1], anchor="w", height=_ROW_H,
        ).grid(row=row_idx, column=0, sticky="w", **pad)

        hi_menu = ctk.CTkOptionMenu(
            self._table, values=[m[0] for m in HI_LO_MODES], width=110, height=_CTRL_H,
            command=lambda _v, n=name: self._on_mode_change(n, "hi"),
        )
        hi_menu.set(next(l for l, v in HI_LO_MODES if v == spec.hi_mode))
        hi_menu.grid(row=row_idx, column=1, **pad)

        hi_extra = self._opt_slot(self._table)
        hi_extra.grid(row=row_idx, column=2, **pad)
        hi_wave = tk.StringVar(value=spec.hi_wave)
        hi_wave_entry = ctk.CTkEntry(
            hi_extra, textvariable=hi_wave, width=96, height=_CTRL_H,
        )
        hi_cond_btn = ctk.CTkButton(
            hi_extra, text=self._cond_btn_label(spec.hi_groups), width=96, height=_CTRL_H,
            command=lambda n=name: self._edit_cond(n, "hi"),
        )

        lo_menu = ctk.CTkOptionMenu(
            self._table, values=[m[0] for m in HI_LO_MODES], width=110, height=_CTRL_H,
            command=lambda _v, n=name: self._on_mode_change(n, "lo"),
        )
        lo_menu.set(next(l for l, v in HI_LO_MODES if v == spec.lo_mode))
        lo_menu.grid(row=row_idx, column=3, **pad)

        lo_extra = self._opt_slot(self._table)
        lo_extra.grid(row=row_idx, column=4, **pad)
        lo_wave = tk.StringVar(value=spec.lo_wave)
        lo_wave_entry = ctk.CTkEntry(
            lo_extra, textvariable=lo_wave, width=96, height=_CTRL_H,
        )
        lo_cond_btn = ctk.CTkButton(
            lo_extra, text=self._cond_btn_label(spec.lo_groups), width=96, height=_CTRL_H,
            command=lambda n=name: self._edit_cond(n, "lo"),
        )

        self._rows[name] = {
            "hi_menu": hi_menu,
            "hi_wave": hi_wave,
            "hi_wave_entry": hi_wave_entry,
            "hi_cond_btn": hi_cond_btn,
            "hi_extra": hi_extra,
            "hi_groups": [list(g) for g in (spec.hi_groups or [])],
            "hi_inv_groups": [list(g) for g in (spec.hi_inv_groups or [])],
            "hi_use_groups": [list(g) for g in (spec.hi_use_groups or [])],
            "lo_menu": lo_menu,
            "lo_wave": lo_wave,
            "lo_wave_entry": lo_wave_entry,
            "lo_cond_btn": lo_cond_btn,
            "lo_extra": lo_extra,
            "lo_groups": [list(g) for g in (spec.lo_groups or [])],
            "lo_inv_groups": [list(g) for g in (spec.lo_inv_groups or [])],
            "lo_use_groups": [list(g) for g in (spec.lo_use_groups or [])],
        }
        self._on_mode_change(name, "hi")
        self._on_mode_change(name, "lo")

    def _cond_btn_label(self, groups: list[list[str]]) -> str:
        n = sum(len(g) for g in groups if g)
        return f"Cond ({n})" if n else "Cond..."

    def _on_mode_change(self, name: str, side: str):
        w = self._rows.get(name)
        if not w:
            return
        mode = self._mode_from_label(w[f"{side}_menu"].get())
        entry = w[f"{side}_wave_entry"]
        btn = w[f"{side}_cond_btn"]
        entry.grid_forget()
        btn.grid_forget()
        if mode == "depends":
            btn.configure(text=self._cond_btn_label(w[f"{side}_groups"]))
            btn.grid(row=0, column=0, sticky="nsew")
        elif mode == "custom":
            entry.grid(row=0, column=0, sticky="nsew")

    def _edit_cond(self, name: str, kind: str):
        w = self._rows[name]
        prefix = f"{kind}_"

        def on_save(groups, inv_groups, use_groups):
            w[f"{prefix}groups"] = groups
            w[f"{prefix}inv_groups"] = inv_groups
            w[f"{prefix}use_groups"] = use_groups
            w[f"{prefix}cond_btn"].configure(text=self._cond_btn_label(groups))

        InputCondEditorDialog(
            self,
            self.config,
            name,
            kind,
            w[f"{prefix}groups"],
            w[f"{prefix}inv_groups"],
            w[f"{prefix}use_groups"],
            on_save,
        )

    def _mode_from_label(self, label: str) -> str:
        for lbl, val in HI_LO_MODES:
            if lbl == label:
                return val
        return "constant_0"

    def _collect_scenario(self) -> WaveDromScenario:
        try:
            steps = max(10, int(self._steps_var.get().strip()))
        except ValueError:
            steps = 200
        try:
            hscale = _norm_hscale(int(self._hscale_var.get().strip()))
        except ValueError:
            hscale = 1
        inputs: dict[str, InputWaveSpec] = {}
        for name, widgets in self._rows.items():
            inputs[name] = InputWaveSpec(
                hi_mode=self._mode_from_label(widgets["hi_menu"].get()),
                hi_wave=widgets["hi_wave"].get().strip() or "0",
                hi_groups=widgets["hi_groups"],
                hi_inv_groups=widgets["hi_inv_groups"],
                hi_use_groups=widgets["hi_use_groups"],
                lo_mode=self._mode_from_label(widgets["lo_menu"].get()),
                lo_wave=widgets["lo_wave"].get().strip() or "0",
                lo_groups=widgets["lo_groups"],
                lo_inv_groups=widgets["lo_inv_groups"],
                lo_use_groups=widgets["lo_use_groups"],
            )
        return WaveDromScenario(steps=steps, inputs=inputs, hscale=hscale)

    def _default_scenario_basename(self) -> str:
        mod = (self.config.module_name or "pwrseq").strip()
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in mod)
        return f"{safe}_wavedrom_scenario.json"

    def _reload_from_scenario(self, scenario: WaveDromScenario) -> None:
        self._saved = merge_scenario_for_config(scenario, self.config)
        self._steps_var.set(str(self._saved.steps))
        self._hscale_var.set(str(self._saved.hscale))
        for w in self._table.winfo_children():
            w.destroy()
        self._rows.clear()
        inputs = [r for r in self.config.rails if r.seq_type == "input"]
        if not inputs:
            ctk.CTkLabel(self._table, text="(no input nodes)").grid(
                row=0, column=0, columnspan=len(_TABLE_COLS), sticky="w", pady=2
            )
        for row_idx, r in enumerate(inputs):
            self._add_input_row(r.name, row_idx)

    def _do_load(self):
        initial = self._last_save_path or self._scenario_path_hint
        if initial and not os.path.isfile(initial):
            initial = os.path.dirname(initial)
        path = filedialog.askopenfilename(
            title="Load WaveDrom scenario",
            initialdir=initial or None,
            filetypes=[
                ("WaveDrom scenario", "*.json"),
                ("All", "*"),
            ],
        )
        if not path:
            return
        try:
            loaded = load_scenario_file(path)
            self._reload_from_scenario(loaded)
            self._last_save_path = path
        except Exception as e:
            messagebox.showerror("Load failed", str(e), parent=self)

    def _write_scenario(self, path: str, scenario: WaveDromScenario) -> None:
        save_scenario_file(path, scenario)
        self._last_save_path = path
        self._status_saved(path)

    def _status_saved(self, path: str) -> None:
        messagebox.showinfo("Saved", f"Settings written to:\n{path}", parent=self)

    def _do_save(self):
        path = self._last_save_path
        if not path:
            hint = self._scenario_path_hint
            if hint and hint.lower().endswith(".json"):
                path = hint
        if not path:
            messagebox.showinfo(
                "Save",
                "No file path yet. Use Save As... first.",
                parent=self,
            )
            return
        try:
            self._write_scenario(path, self._collect_scenario())
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self)

    def _do_save_as(self):
        scenario = self._collect_scenario()
        initial = self._last_save_path or self._scenario_path_hint
        if not initial or not str(initial).lower().endswith(".json"):
            initial = self._default_scenario_basename()
        path = filedialog.asksaveasfilename(
            title="Save WaveDrom scenario as",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) if os.path.dirname(initial) else None,
            defaultextension=".json",
            filetypes=[
                ("WaveDrom scenario", "*.json"),
                ("All", "*"),
            ],
        )
        if not path:
            return
        try:
            self._write_scenario(path, scenario)
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self)

    def _do_export(self):
        self.on_export(self._collect_scenario())
