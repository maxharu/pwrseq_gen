"""
Power Sequence Config GUI
Per 需求表: seq_type output | input, Hi/Lo Dep, Debounce, Pulse
"""
import json
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config_models import PowerSeqConfig, PowerRail
from validator import validate
from verilog_generator import generate_verilog

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SEQ_TYPE_LABELS = {"output": "Output", "input": "Input"}
DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"


def _safe_int(s: str, default: int) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default


class RailEditorFrame(ctk.CTkFrame):
    """Single node editor (F-GUI-02)"""

    def __init__(self, master, rail: PowerRail, all_rails: list[PowerRail], config: PowerSeqConfig,
                 get_pulses=None, on_apply_changes=None, **kwargs):
        super().__init__(master, **kwargs)
        self.rail = rail
        self.all_rails = [r for r in all_rails if r.name != rail.name]
        self.name_to_rail = {r.name: r for r in all_rails}
        self.config = config
        self.get_pulses = get_pulses or (lambda: getattr(config, "pulses", None) or ["iPulse_1us"])
        self.on_apply_changes = on_apply_changes
        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(0, 8))
        type_label = SEQ_TYPE_LABELS.get(self.rail.seq_type, self.rail.seq_type)
        ctk.CTkLabel(header, text=f"{self.rail.name} [{type_label}]", font=("", 14, "bold")).pack(side="left")

        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        ctk.CTkLabel(row1, text="Name:", width=80).pack(side="left", padx=(0, 4))
        self.entry_name = ctk.CTkEntry(row1, width=120)
        self.entry_name.insert(0, self.rail.name)
        self.entry_name.pack(side="left", padx=(0, 8))
        self.btn_apply = ctk.CTkButton(row1, text="Apply", width=50, command=self._on_apply_changes)
        self.btn_apply.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(row1, text="Type:", width=40).pack(side="left", padx=(0, 4))
        self.var_type = ctk.StringVar(value=self.rail.seq_type)
        for st, label in SEQ_TYPE_LABELS.items():
            ctk.CTkRadioButton(row1, text=label, variable=self.var_type, value=st).pack(side="left", padx=(0, 8))
        self.var_type.trace_add("write", lambda *_: self._on_type_change())

        self.row2 = ctk.CTkFrame(self, fg_color="transparent")
        self.row2.pack(fill="x", pady=2)
        ctk.CTkLabel(self.row2, text="CYCLE_HI:", width=80).pack(side="left", padx=(0, 4))
        self.entry_hi = ctk.CTkEntry(self.row2, width=60)
        self.entry_hi.insert(0, str(self.rail.cycle_hi))
        self.entry_hi.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row2, text="CYCLE_LO:", width=80).pack(side="left", padx=(0, 4))
        self.entry_lo = ctk.CTkEntry(self.row2, width=60)
        self.entry_lo.insert(0, str(self.rail.cycle_lo))
        self.entry_lo.pack(side="left")

        self.row2b = ctk.CTkFrame(self, fg_color="transparent")
        self.row2b.pack(fill="x", pady=2)
        pulses = list(self.get_pulses())
        for v in (getattr(self.rail, "pulse_hi", "iPulse_1us") or "iPulse_1us",
                  getattr(self.rail, "pulse_lo", "iPulse_1us") or "iPulse_1us",
                  getattr(self.rail, "pulse_force", "iPulse_1us") or "iPulse_1us"):
            if v and v not in pulses:
                pulses.append(v)
        ctk.CTkLabel(self.row2b, text="Pulse Hi:", width=80).pack(side="left", padx=(0, 4))
        self.var_pulse_hi = ctk.StringVar(value=getattr(self.rail, "pulse_hi", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(self.row2b, values=pulses, variable=self.var_pulse_hi, width=100).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row2b, text="Pulse Lo:", width=80).pack(side="left", padx=(0, 4))
        self.var_pulse_lo = ctk.StringVar(value=getattr(self.rail, "pulse_lo", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(self.row2b, values=pulses, variable=self.var_pulse_lo, width=100).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row2b, text="Pulse Force:", width=80).pack(side="left", padx=(0, 4))
        self.var_pulse_force = ctk.StringVar(value=getattr(self.rail, "pulse_force", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(self.row2b, values=pulses, variable=self.var_pulse_force, width=100).pack(side="left")

        self.row3 = ctk.CTkFrame(self, fg_color="transparent")
        self.dep_hi_groups = [list(g) for g in self.rail.get_hi_groups()] if self.rail.get_hi_groups() else [[]]
        self.dep_lo_groups = [list(g) for g in self.rail.get_lo_groups()] if self.rail.get_lo_groups() else [[]]
        if not self.dep_hi_groups:
            self.dep_hi_groups = [[]]
        if not self.dep_lo_groups:
            self.dep_lo_groups = [[]]
        self.dep_hi_inv_vars = {}
        self.dep_lo_inv_vars = {}
        self.dep_hi_use_vars = {}
        self.dep_lo_use_vars = {}
        self.dep_hi_rows = {}
        self.dep_lo_rows = {}
        self.hi_group_frames = []
        self.lo_group_frames = []

        row3a = ctk.CTkFrame(self.row3, fg_color="transparent")
        row3a.pack(fill="x", pady=2)
        ctk.CTkLabel(row3a, text="Hi Dep:", width=80).pack(side="left", padx=(0, 4), anchor="n")
        ctk.CTkLabel(row3a, text="(group &, groups |)", font=("", 10), text_color="gray").pack(side="left", padx=(0, 8))
        ctk.CTkButton(row3a, text="+ Add Group", width=70, command=self._add_hi_group).pack(side="left", padx=(0, 8))
        self.hi_groups_frame = ctk.CTkFrame(row3a, fg_color="transparent")
        self.hi_groups_frame.pack(fill="x", pady=(4, 0))
        self._rebuild_hi_groups_ui()

        row3b = ctk.CTkFrame(self.row3, fg_color="transparent")
        row3b.pack(fill="x", pady=2)
        ctk.CTkLabel(row3b, text="Lo Dep:", width=80).pack(side="left", padx=(0, 4), anchor="n")
        ctk.CTkLabel(row3b, text="(group &, groups |)", font=("", 10), text_color="gray").pack(side="left", padx=(0, 8))
        ctk.CTkButton(row3b, text="+ Add Group", width=70, command=self._add_lo_group).pack(side="left", padx=(0, 8))
        self.lo_groups_frame = ctk.CTkFrame(row3b, fg_color="transparent")
        self.lo_groups_frame.pack(fill="x", pady=(4, 0))
        self._rebuild_lo_groups_ui()

        self.row_deb = ctk.CTkFrame(self, fg_color="transparent")
        self.row_deb.pack(fill="x", pady=2)
        self.var_deb_enable = ctk.BooleanVar(value=getattr(self.rail, "deb_enable", False))
        ctk.CTkCheckBox(self.row_deb, text="Debounce", variable=self.var_deb_enable, width=90).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row_deb, text="INIT:", width=50).pack(side="left", padx=(0, 4))
        self.entry_deb_init = ctk.CTkEntry(self.row_deb, width=40)
        self.entry_deb_init.insert(0, str(getattr(self.rail, "deb_init", 0)))
        self.entry_deb_init.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(self.row_deb, text="CYCLE_HI:", width=70).pack(side="left", padx=(0, 4))
        self.entry_deb_cycle_hi = ctk.CTkEntry(self.row_deb, width=40)
        self.entry_deb_cycle_hi.insert(0, str(getattr(self.rail, "deb_cycle_hi", 2)))
        self.entry_deb_cycle_hi.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(self.row_deb, text="CYCLE_LO:", width=70).pack(side="left", padx=(0, 4))
        self.entry_deb_cycle_lo = ctk.CTkEntry(self.row_deb, width=40)
        self.entry_deb_cycle_lo.insert(0, str(getattr(self.rail, "deb_cycle_lo", 2)))
        self.entry_deb_cycle_lo.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(self.row_deb, text="Pulse:", width=50).pack(side="left", padx=(0, 4))
        deb_pulses = list(self.get_pulses())
        deb_pulse_val = getattr(self.rail, "deb_pulse", "iPulse_1us") or "iPulse_1us"
        if deb_pulse_val not in deb_pulses:
            deb_pulses.append(deb_pulse_val)
        self.var_deb_pulse = ctk.StringVar(value=deb_pulse_val)
        ctk.CTkComboBox(self.row_deb, values=deb_pulses, variable=self.var_deb_pulse, width=100).pack(side="left")

        self.row3.pack(fill="x", pady=2)
        self._on_type_change()

    def _get_dep_combo_values(self) -> list[str]:
        return [r.name for r in self.all_rails] + ["High", "Low"]

    def _rebuild_hi_groups_ui(self):
        for w in self.hi_groups_frame.winfo_children():
            w.destroy()
        self.hi_group_frames.clear()
        for gi, group in enumerate(self.dep_hi_groups):
            self._add_hi_group_ui(gi)

    def _add_hi_group_ui(self, group_idx: int):
        group = self.dep_hi_groups[group_idx]
        frame = ctk.CTkFrame(self.hi_groups_frame, fg_color=("gray95", "gray20"))
        frame.pack(fill="x", pady=4, padx=(20, 0))
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(header, text=f"Group {group_idx + 1}", width=50).pack(side="left", padx=(0, 8))
        combo_vals = self._get_dep_combo_values()
        combo = ctk.CTkComboBox(header, values=combo_vals, width=120)
        combo.pack(side="left", padx=(0, 8))
        if combo_vals:
            combo.set(combo_vals[0])
        ctk.CTkButton(header, text="+ Add", width=60, command=lambda: self._add_hi_dep_to_group(group_idx)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(header, text="Del Group", width=60, command=lambda: self._remove_hi_group(group_idx)).pack(side="left")
        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        list_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.hi_group_frames.append({"frame": frame, "combo": combo, "list_frame": list_frame})
        for name in group:
            self._add_hi_dep_row_to_group(group_idx, name)

    def _add_hi_dep_row_to_group(self, group_idx: int, name: str):
        display_name = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
        is_const = name in (DEP_HIGH, DEP_LOW)
        dep_rail = self.name_to_rail.get(name)
        can_use_hi_lo = dep_rail is not None and dep_rail.has_pseqcell
        if name not in self.dep_hi_inv_vars:
            self.dep_hi_inv_vars[name] = ctk.BooleanVar(value=False if is_const else self.rail.depends_on_hi_inv.get(name, False))
        if name not in self.dep_hi_use_vars:
            _use_display = {"self": "Node", "hi": "Hi Dep", "lo": "Lo Dep"}
            self.dep_hi_use_vars[name] = ctk.StringVar(value=_use_display.get(self.rail.depends_on_hi_use.get(name, "self"), "Node"))
        list_frame = self.hi_group_frames[group_idx]["list_frame"]
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        self.dep_hi_rows[(group_idx, name)] = row
        ctk.CTkLabel(row, text=display_name, width=100).pack(side="left", padx=(0, 4))
        if not is_const:
            ctk.CTkCheckBox(row, text="Inv", variable=self.dep_hi_inv_vars[name], width=50).pack(side="left", padx=(0, 4))
        if can_use_hi_lo:
            ctk.CTkComboBox(row, values=["Node", "Hi Dep", "Lo Dep"], variable=self.dep_hi_use_vars[name], width=90).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row, text="Del", width=50, command=lambda: self._remove_hi_dep_from_group(group_idx, name)).pack(side="left")

    def _add_hi_dep_to_group(self, group_idx: int):
        gf = self.hi_group_frames[group_idx]
        sel = gf["combo"].get()
        if not sel:
            return
        dep_key = DEP_HIGH if sel == "High" else (DEP_LOW if sel == "Low" else sel)
        self.dep_hi_groups[group_idx].append(dep_key)
        self._add_hi_dep_row_to_group(group_idx, dep_key)

    def _remove_hi_dep_from_group(self, group_idx: int, name: str):
        if group_idx < len(self.dep_hi_groups) and name in self.dep_hi_groups[group_idx]:
            self.dep_hi_groups[group_idx].remove(name)
            key = (group_idx, name)
            if key in self.dep_hi_rows:
                self.dep_hi_rows[key].destroy()
                del self.dep_hi_rows[key]
            if not any(name in g for g in self.dep_hi_groups):
                self.dep_hi_inv_vars.pop(name, None)
                self.dep_hi_use_vars.pop(name, None)

    def _remove_hi_group(self, group_idx: int):
        if group_idx < len(self.dep_hi_groups):
            removed_names = set(self.dep_hi_groups[group_idx])
            del self.dep_hi_groups[group_idx]
            for name in removed_names:
                if not any(name in g for g in self.dep_hi_groups):
                    self.dep_hi_inv_vars.pop(name, None)
                    self.dep_hi_use_vars.pop(name, None)
            self._rebuild_hi_groups_ui()

    def _add_hi_group(self):
        self.dep_hi_groups.append([])
        self._rebuild_hi_groups_ui()

    def _rebuild_lo_groups_ui(self):
        for w in self.lo_groups_frame.winfo_children():
            w.destroy()
        self.lo_group_frames.clear()
        for gi, group in enumerate(self.dep_lo_groups):
            self._add_lo_group_ui(gi)

    def _add_lo_group_ui(self, group_idx: int):
        group = self.dep_lo_groups[group_idx]
        frame = ctk.CTkFrame(self.lo_groups_frame, fg_color=("gray95", "gray20"))
        frame.pack(fill="x", pady=4, padx=(20, 0))
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(header, text=f"Group {group_idx + 1}", width=50).pack(side="left", padx=(0, 8))
        combo_vals = self._get_dep_combo_values()
        combo = ctk.CTkComboBox(header, values=combo_vals, width=120)
        combo.pack(side="left", padx=(0, 8))
        if combo_vals:
            combo.set(combo_vals[0])
        ctk.CTkButton(header, text="+ Add", width=60, command=lambda: self._add_lo_dep_to_group(group_idx)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(header, text="Del Group", width=60, command=lambda: self._remove_lo_group(group_idx)).pack(side="left")
        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        list_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.lo_group_frames.append({"frame": frame, "combo": combo, "list_frame": list_frame})
        for name in group:
            self._add_lo_dep_row_to_group(group_idx, name)

    def _add_lo_dep_row_to_group(self, group_idx: int, name: str):
        display_name = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
        is_const = name in (DEP_HIGH, DEP_LOW)
        dep_rail = self.name_to_rail.get(name)
        can_use_hi_lo = dep_rail is not None and dep_rail.has_pseqcell
        if name not in self.dep_lo_inv_vars:
            self.dep_lo_inv_vars[name] = ctk.BooleanVar(value=False if is_const else self.rail.depends_on_lo_inv.get(name, False))
        if name not in self.dep_lo_use_vars:
            _use_display = {"self": "Node", "hi": "Hi Dep", "lo": "Lo Dep"}
            self.dep_lo_use_vars[name] = ctk.StringVar(value=_use_display.get(self.rail.depends_on_lo_use.get(name, "self"), "Node"))
        list_frame = self.lo_group_frames[group_idx]["list_frame"]
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        self.dep_lo_rows[(group_idx, name)] = row
        ctk.CTkLabel(row, text=display_name, width=100).pack(side="left", padx=(0, 4))
        if not is_const:
            ctk.CTkCheckBox(row, text="Inv", variable=self.dep_lo_inv_vars[name], width=50).pack(side="left", padx=(0, 4))
        if can_use_hi_lo:
            ctk.CTkComboBox(row, values=["Node", "Hi Dep", "Lo Dep"], variable=self.dep_lo_use_vars[name], width=90).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row, text="Del", width=50, command=lambda: self._remove_lo_dep_from_group(group_idx, name)).pack(side="left")

    def _add_lo_dep_to_group(self, group_idx: int):
        gf = self.lo_group_frames[group_idx]
        sel = gf["combo"].get()
        if not sel:
            return
        dep_key = DEP_HIGH if sel == "High" else (DEP_LOW if sel == "Low" else sel)
        self.dep_lo_groups[group_idx].append(dep_key)
        self._add_lo_dep_row_to_group(group_idx, dep_key)

    def _remove_lo_dep_from_group(self, group_idx: int, name: str):
        if group_idx < len(self.dep_lo_groups) and name in self.dep_lo_groups[group_idx]:
            self.dep_lo_groups[group_idx].remove(name)
            key = (group_idx, name)
            if key in self.dep_lo_rows:
                self.dep_lo_rows[key].destroy()
                del self.dep_lo_rows[key]
            if not any(name in g for g in self.dep_lo_groups):
                self.dep_lo_inv_vars.pop(name, None)
                self.dep_lo_use_vars.pop(name, None)

    def _remove_lo_group(self, group_idx: int):
        if group_idx < len(self.dep_lo_groups):
            removed_names = set(self.dep_lo_groups[group_idx])
            del self.dep_lo_groups[group_idx]
            for name in removed_names:
                if not any(name in g for g in self.dep_lo_groups):
                    self.dep_lo_inv_vars.pop(name, None)
                    self.dep_lo_use_vars.pop(name, None)
            self._rebuild_lo_groups_ui()

    def _add_lo_group(self):
        self.dep_lo_groups.append([])
        self._rebuild_lo_groups_ui()

    def _on_apply_changes(self):
        if self.on_apply_changes:
            old_name = self.rail.name
            new_name = self.entry_name.get().strip()
            old_type = self.rail.seq_type
            new_type = self.var_type.get()
            self.on_apply_changes(old_name, new_name, old_type, new_type)

    def _on_type_change(self):
        is_input = self.var_type.get() == "input"
        if is_input:
            self.row2.pack_forget()
            self.row2b.pack_forget()
            self.row3.pack_forget()
            self.row_deb.pack(fill="x", pady=2)
            self.dep_hi_groups = [[]]
            self.dep_lo_groups = [[]]
            self.dep_hi_inv_vars.clear()
            self.dep_lo_inv_vars.clear()
            self.dep_hi_use_vars.clear()
            self.dep_lo_use_vars.clear()
            self.dep_hi_rows.clear()
            self.dep_lo_rows.clear()
        else:
            self.row2.pack(fill="x", pady=2)
            self.row2b.pack(fill="x", pady=2)
            self.row3.pack(fill="x", pady=2)
            self.row_deb.pack_forget()
            if not self.dep_hi_groups or self.dep_hi_groups == [[]]:
                self.dep_hi_groups = [list(g) for g in self.rail.get_hi_groups()] if self.rail.get_hi_groups() else [[]]
                if not self.dep_hi_groups:
                    self.dep_hi_groups = [[]]
                self._rebuild_hi_groups_ui()
            if not self.dep_lo_groups or self.dep_lo_groups == [[]]:
                self.dep_lo_groups = [list(g) for g in self.rail.get_lo_groups()] if self.rail.get_lo_groups() else [[]]
                if not self.dep_lo_groups:
                    self.dep_lo_groups = [[]]
                self._rebuild_lo_groups_ui()

    def get_rail(self) -> PowerRail:
        rail_name = self.entry_name.get().strip()
        try:
            cycle_hi = int(self.entry_hi.get())
        except ValueError:
            cycle_hi = self.rail.cycle_hi
        try:
            cycle_lo = int(self.entry_lo.get())
        except ValueError:
            cycle_lo = self.rail.cycle_lo
        groups_hi = [list(g) for g in self.dep_hi_groups if g]
        groups_lo = [list(g) for g in self.dep_lo_groups if g]
        flat_hi = [d for g in groups_hi for d in g]
        flat_lo = [d for g in groups_lo for d in g]
        depends_on_hi_inv = {n: self.dep_hi_inv_vars[n].get() for n in flat_hi if n in self.dep_hi_inv_vars}
        depends_on_lo_inv = {n: self.dep_lo_inv_vars[n].get() for n in flat_lo if n in self.dep_lo_inv_vars}
        _use_reverse = {"Node": "self", "Hi Dep": "hi", "Lo Dep": "lo"}
        depends_on_hi_use = {n: _use_reverse.get(self.dep_hi_use_vars[n].get(), "self") for n in flat_hi if n in self.dep_hi_use_vars}
        depends_on_lo_use = {n: _use_reverse.get(self.dep_lo_use_vars[n].get(), "self") for n in flat_lo if n in self.dep_lo_use_vars}
        seq_type = self.var_type.get()
        if seq_type == "input":
            cycle_hi, cycle_lo = 0, 0
            groups_hi, groups_lo = [], []
            flat_hi, flat_lo = [], []
        return PowerRail(
            name=rail_name or self.rail.name,
            seq_type=seq_type,
            depends_on=flat_hi if seq_type != "input" else [],
            depends_on_hi=flat_hi if seq_type != "input" else [],
            depends_on_lo=flat_lo if seq_type != "input" else [],
            depends_on_hi_groups=groups_hi if seq_type != "input" else [],
            depends_on_lo_groups=groups_lo if seq_type != "input" else [],
            depends_on_hi_inv=depends_on_hi_inv if seq_type != "input" else {},
            depends_on_lo_inv=depends_on_lo_inv if seq_type != "input" else {},
            depends_on_hi_use=depends_on_hi_use if seq_type != "input" else {},
            depends_on_lo_use=depends_on_lo_use if seq_type != "input" else {},
            pulse_hi=self.var_pulse_hi.get() if seq_type != "input" else "iPulse_1us",
            pulse_lo=self.var_pulse_lo.get() if seq_type != "input" else "iPulse_1us",
            pulse_force=self.var_pulse_force.get() if seq_type != "input" else "iPulse_1us",
            deb_enable=self.var_deb_enable.get() if seq_type == "input" else False,
            deb_init=_safe_int(self.entry_deb_init.get(), 0) if seq_type == "input" else 0,
            deb_cycle_hi=_safe_int(self.entry_deb_cycle_hi.get(), 2) if seq_type == "input" else 2,
            deb_cycle_lo=_safe_int(self.entry_deb_cycle_lo.get(), 2) if seq_type == "input" else 2,
            deb_cycle_sync=2,
            deb_pulse=self.var_deb_pulse.get() if seq_type == "input" else "iPulse_1us",
            cycle_hi=cycle_hi,
            cycle_lo=cycle_lo,
            cycle_force=self.rail.cycle_force,
            recover=self.rail.recover,
            init=self.rail.init,
            force_val=self.rail.force_val,
            cycle_sync=self.rail.cycle_sync,
            od=self.rail.od,
        )


class PowerSeqGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Power Sequence Config v1.0")
        self.geometry("950x750")
        self.config = PowerSeqConfig()
        self._build_ui()

    def _build_ui(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(toolbar, text="+ Add", command=self._add_rail, width=80).pack(side="left", padx=(0, 8))
        ctk.CTkButton(toolbar, text="- Delete", command=self._delete_selected, width=100).pack(side="left", padx=(0, 8))
        ctk.CTkButton(toolbar, text="Load JSON", command=self._load_json, width=100).pack(side="left", padx=(0, 8))
        ctk.CTkButton(toolbar, text="Save JSON", command=self._save_json, width=100).pack(side="left", padx=(0, 8))
        ctk.CTkButton(toolbar, text="Generate Verilog", command=self._generate_verilog, width=120).pack(side="left", padx=(0, 8))

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ctk.CTkFrame(main, width=220, fg_color=("gray90", "gray17"))
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        ctk.CTkLabel(left, text="Sequence Node", font=("", 14, "bold")).pack(pady=(10, 8))
        self.rail_listbox = tk.Listbox(left, font=("Consolas", 10), selectmode="single", height=14)
        self.rail_listbox.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(left, text="Timing Pulse", font=("", 12, "bold")).pack(pady=(8, 4))
        pulse_frame = ctk.CTkFrame(left, fg_color="transparent")
        pulse_frame.pack(fill="x")
        self.pulse_entry = ctk.CTkEntry(pulse_frame, width=100, placeholder_text="New pulse name")
        self.pulse_entry.pack(side="left", padx=(0, 4))
        ctk.CTkButton(pulse_frame, text="+ Add", width=60, command=self._add_pulse).pack(side="left")
        self.pulse_listbox = tk.Listbox(left, font=("Consolas", 9), selectmode="single", height=4)
        self.pulse_listbox.pack(fill="x", pady=(0, 4))
        ctk.CTkButton(left, text="- Delete Pulse", width=140, command=self._delete_pulse).pack(pady=(0, 8))
        self.rail_listbox.bind("<<ListboxSelect>>", self._on_rail_select)
        self._drag_start_index = None
        self.rail_listbox.bind("<ButtonPress-1>", self._on_listbox_press)
        self.rail_listbox.bind("<ButtonRelease-1>", self._on_listbox_release)
        self._refresh_pulse_listbox()

        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        self.editor_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.editor_scroll.pack(fill="both", expand=True)
        self.editor_frames = []
        self._refresh_editors()

        self.msg_frame = ctk.CTkFrame(right, fg_color=("gray90", "gray17"))
        self.msg_frame.pack(fill="x", pady=(10, 0))
        self.msg_label = ctk.CTkLabel(self.msg_frame, text="", wraplength=600, justify="left")
        self.msg_label.pack(padx=10, pady=10, anchor="w")
        self._update_validation_msg()

    def _refresh_pulse_listbox(self):
        self.pulse_listbox.delete(0, tk.END)
        pulses = getattr(self.config, "pulses", None) or ["iPulse_1us"]
        for p in pulses:
            self.pulse_listbox.insert(tk.END, p if p else "iPulse_1us")

    def _add_pulse(self):
        name = self.pulse_entry.get().strip()
        if not name:
            messagebox.showwarning("Notice", "Enter pulse name")
            return
        self.config = self._collect_config()
        pulses = getattr(self.config, "pulses", None) or ["iPulse_1us"]
        if name in pulses:
            messagebox.showwarning("Notice", f"Pulse '{name}' already exists")
            return
        pulses = list(pulses)
        pulses.append(name)
        self.config.pulses = pulses
        self._refresh_pulse_listbox()
        self._refresh_editors()
        self.pulse_entry.delete(0, tk.END)

    def _delete_pulse(self):
        sel = self.pulse_listbox.curselection()
        if not sel:
            messagebox.showinfo("Notice", "Select a pulse to delete")
            return
        idx = sel[0]
        self.config = self._collect_config()
        pulses = getattr(self.config, "pulses", None) or ["iPulse_1us"]
        name = pulses[idx] if idx < len(pulses) else None
        if not name:
            return
        if len(pulses) <= 1:
            messagebox.showwarning("Notice", "At least one pulse required")
            return
        pulses = [p for p in pulses if p != name]
        fallback = pulses[0] if pulses else "iPulse_1us"
        self.config.pulses = pulses
        for r in self.config.rails:
            if getattr(r, "pulse_hi", "iPulse_1us") == name:
                r.pulse_hi = fallback
            if getattr(r, "pulse_lo", "iPulse_1us") == name:
                r.pulse_lo = fallback
            if getattr(r, "pulse_force", "iPulse_1us") == name:
                r.pulse_force = fallback
        self._refresh_pulse_listbox()
        self._refresh_editors()
        self._update_validation_msg()

    def _refresh_editors(self):
        for w in self.editor_scroll.winfo_children():
            w.destroy()
        self.editor_frames.clear()
        def get_pulses():
            return getattr(self.config, "pulses", None) or ["iPulse_1us"]
        for r in self.config.rails:
            f = RailEditorFrame(self.editor_scroll, r, self.config.rails, self.config,
                               get_pulses=get_pulses, on_apply_changes=self._apply_changes)
            f.pack(fill="x", pady=8, padx=4)
            self.editor_frames.append(f)
        self.rail_listbox.delete(0, tk.END)
        for r in self.config.rails:
            t = SEQ_TYPE_LABELS.get(r.seq_type, r.seq_type)[:16]
            label = f"{r.name} [{t}]"
            self.rail_listbox.insert(tk.END, label)

    def _on_rail_select(self, event):
        sel = self.rail_listbox.curselection()
        if sel and sel[0] < len(self.editor_frames):
            self.editor_frames[sel[0]].focus_set()

    def _on_listbox_press(self, event):
        idx = self.rail_listbox.nearest(event.y)
        if 0 <= idx < self.rail_listbox.size():
            self._drag_start_index = idx

    def _on_listbox_release(self, event):
        start_idx = self._drag_start_index
        self._drag_start_index = None
        if start_idx is None:
            return
        end_idx = self.rail_listbox.nearest(event.y)
        if end_idx < 0 or end_idx >= len(self.config.rails) or end_idx == start_idx:
            return
        self.config = self._collect_config()
        rail = self.config.rails.pop(start_idx)
        self.config.rails.insert(end_idx, rail)
        self._refresh_editors()
        self._update_validation_msg()

    def _add_rail(self):
        self.config = self._collect_config()
        n = len(self.config.rails) + 1
        name = f"SIG_{n}"
        while any(r.name == name for r in self.config.rails):
            n += 1
            name = f"SIG_{n}"
        self.config.rails.append(PowerRail(name=name, seq_type="output"))
        self._refresh_editors()
        self._update_validation_msg()

    def _delete_selected(self):
        self.config = self._collect_config()
        sel = self.rail_listbox.curselection()
        if not sel:
            messagebox.showinfo("Notice", "Select a node to delete")
            return
        idx = sel[0]
        if 0 <= idx < len(self.config.rails):
            del self.config.rails[idx]
            self._refresh_editors()
            self._update_validation_msg()

    def _collect_config(self) -> PowerSeqConfig:
        return PowerSeqConfig(
            rails=[f.get_rail() for f in self.editor_frames],
            module_name=self.config.module_name,
            clock_freq_mhz=self.config.clock_freq_mhz,
            pulse_period_ns=self.config.pulse_period_ns,
            pulses=getattr(self.config, "pulses", None) or ["iPulse_1us"],
        )

    def _apply_changes(self, old_name: str, new_name: str, old_type: str, new_type: str):
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Notice", "Name cannot be empty")
            return
        if new_name != old_name and any(r.name == new_name for r in self.config.rails):
            messagebox.showerror("Error", f"Name '{new_name}' already exists")
            return
        target_idx = next((i for i, r in enumerate(self.config.rails) if r.name == old_name), None)
        if target_idx is not None:
            applied_rail = self.editor_frames[target_idx].get_rail()
            self.config.rails[target_idx] = applied_rail
        if new_name != old_name or new_type != old_type:
            for r in self.config.rails:
                r.depends_on_hi = [new_name if n == old_name else n for n in r.depends_on_hi]
                r.depends_on_lo = [new_name if n == old_name else n for n in r.depends_on_lo]
                r.depends_on_hi_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_hi_groups]
                r.depends_on_lo_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_lo_groups]
                r.depends_on_hi_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_hi_inv.items()}
                r.depends_on_lo_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_lo_inv.items()}
                r.depends_on_hi_use = {new_name if k == old_name else k: v for k, v in r.depends_on_hi_use.items()}
                r.depends_on_lo_use = {new_name if k == old_name else k: v for k, v in r.depends_on_lo_use.items()}
        self._refresh_editors()
        self._update_validation_msg()

    def _update_validation_msg(self):
        config = self._collect_config()
        ok, errs = validate(config)
        self.msg_label.configure(text="OK" if ok else "Error: " + "\n".join(errs), text_color="green" if ok else "red")

    def _load_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path:
            try:
                self.config = PowerSeqConfig.from_dict(json.load(open(path, encoding="utf-8")))
                self._refresh_pulse_listbox()
                self._refresh_editors()
                self._update_validation_msg()
                messagebox.showinfo("Success", "Loaded")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _save_json(self):
        config = self._collect_config()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            try:
                json.dump(config.to_dict(), open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                messagebox.showinfo("Success", "Saved")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _generate_verilog(self):
        config = self._collect_config()
        ok, errs = validate(config)
        if not ok:
            messagebox.showerror("Validation Failed", "\n".join(errs))
            return
        path = filedialog.asksaveasfilename(defaultextension=".v", filetypes=[("Verilog", "*.v")])
        if path:
            try:
                open(path, "w", encoding="utf-8").write(generate_verilog(config, output_filename=path))
                messagebox.showinfo("Success", f"Generated: {path}")
            except Exception as e:
                messagebox.showerror("Error", str(e))


def run_gui():
    app = PowerSeqGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
