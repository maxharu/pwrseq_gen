"""
Power Sequence Config GUI
Per 需求表: seq_type output | input, Hi/Lo Cond, Debounce, Pulse
"""
import json
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# 關閉自動 DPI 縮放，可避免視窗縮放時畫面變淡（與下拉選單無關，為 CTk scaling 行為）。
# 若高解析度螢幕下畫面略為模糊，可註解掉下行。
ctk.deactivate_automatic_dpi_awareness()

from config_models import PowerSeqConfig, PowerRail
from drawio_export import generate_drawio
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
        self.entry_name.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(row1, text="Type:", width=40).pack(side="left", padx=(0, 4))
        self.var_type = ctk.StringVar(value=self.rail.seq_type)
        for st, label in SEQ_TYPE_LABELS.items():
            ctk.CTkRadioButton(row1, text=label, variable=self.var_type, value=st).pack(side="left", padx=(0, 8))
        self.btn_apply = ctk.CTkButton(row1, text="Apply", width=50, command=self._on_apply_changes)
        self.btn_apply.pack(side="left", padx=(8, 0))
        self.var_type.trace_add("write", lambda *_: self._on_type_change())

        self.row2 = ctk.CTkFrame(self, fg_color="transparent")
        self.row2.pack(fill="x", pady=2)
        ctk.CTkLabel(self.row2, text="CYCLE_HI:", width=80).pack(side="left", padx=(0, 4))
        self.entry_hi = ctk.CTkEntry(self.row2, width=100)
        self.entry_hi.insert(0, str(self.rail.cycle_hi))
        self.entry_hi.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row2, text="CYCLE_LO:", width=80).pack(side="left", padx=(0, 4))
        self.entry_lo = ctk.CTkEntry(self.row2, width=100)
        self.entry_lo.insert(0, str(self.rail.cycle_lo))
        self.entry_lo.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row2, text="INIT:", width=80).pack(side="left", padx=(0, 4))
        self.var_pseq_init = ctk.StringVar(value="1" if getattr(self.rail, "init", 0) == 1 else "0")
        ctk.CTkComboBox(self.row2, values=["0", "1"], variable=self.var_pseq_init, width=100).pack(side="left")

        self.row2b = ctk.CTkFrame(self, fg_color="transparent")
        self.row2b.pack(fill="x", pady=2)
        pulses = list(self.get_pulses()) + ["High"]
        for v in (getattr(self.rail, "pulse_hi", "iPulse_1us") or "iPulse_1us",
                  getattr(self.rail, "pulse_lo", "iPulse_1us") or "iPulse_1us",
                  getattr(self.rail, "pulse_force", "iPulse_1us") or "iPulse_1us"):
            if v and v not in pulses:
                pulses.append(v)
        ctk.CTkLabel(self.row2b, text="Timing Hi:", width=80).pack(side="left", padx=(0, 4))
        self.var_pulse_hi = ctk.StringVar(value=getattr(self.rail, "pulse_hi", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(self.row2b, values=pulses, variable=self.var_pulse_hi, width=100).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row2b, text="Timing Lo:", width=80).pack(side="left", padx=(0, 4))
        self.var_pulse_lo = ctk.StringVar(value=getattr(self.rail, "pulse_lo", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(self.row2b, values=pulses, variable=self.var_pulse_lo, width=100).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.row2b, text="Timing Force:", width=80).pack(side="left", padx=(0, 4))
        self.var_pulse_force = ctk.StringVar(value=getattr(self.rail, "pulse_force", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(self.row2b, values=pulses, variable=self.var_pulse_force, width=100).pack(side="left")

        self.row3 = ctk.CTkFrame(self, fg_color="transparent")
        self.dep_hi_groups = [list(g) for g in self.rail.get_hi_groups()] if self.rail.get_hi_groups() else [[]]
        self.dep_lo_groups = [list(g) for g in self.rail.get_lo_groups()] if self.rail.get_lo_groups() else [[]]
        self.dep_force_groups = [list(g) for g in self.rail.get_force_groups()] if self.rail.get_force_groups() else [[]]
        if not self.dep_hi_groups:
            self.dep_hi_groups = [[]]
        if not self.dep_lo_groups:
            self.dep_lo_groups = [[]]
        if not self.dep_force_groups:
            self.dep_force_groups = [[]]
        self.dep_hi_inv_vars = {}
        self.dep_lo_inv_vars = {}
        self.dep_force_inv_vars = {}
        self.dep_hi_use_vars = {}
        self.dep_lo_use_vars = {}
        self.dep_force_use_vars = {}
        self.dep_hi_rows = {}
        self.dep_lo_rows = {}
        self.dep_force_rows = {}
        self.hi_group_frames = []
        self.lo_group_frames = []
        self.force_group_frames = []

        row3a = ctk.CTkFrame(self.row3, fg_color="transparent")
        row3a.pack(fill="x", pady=2)
        ctk.CTkLabel(row3a, text="Hi Cond:", width=80).pack(side="left", padx=(0, 4), anchor="n")
        ctk.CTkLabel(row3a, text="(group &, groups |)", font=("", 10), text_color="gray").pack(side="left", padx=(0, 8))
        ctk.CTkButton(row3a, text="+ Add Group", width=70, command=self._add_hi_group).pack(side="left", padx=(0, 8))
        self.hi_groups_frame = ctk.CTkFrame(row3a, fg_color="transparent")
        self.hi_groups_frame.pack(fill="x", pady=(4, 0))
        self._rebuild_hi_groups_ui()

        row3b = ctk.CTkFrame(self.row3, fg_color="transparent")
        row3b.pack(fill="x", pady=2)
        ctk.CTkLabel(row3b, text="Lo Cond:", width=80).pack(side="left", padx=(0, 4), anchor="n")
        ctk.CTkLabel(row3b, text="(group &, groups |)", font=("", 10), text_color="gray").pack(side="left", padx=(0, 8))
        ctk.CTkButton(row3b, text="+ Add Group", width=70, command=self._add_lo_group).pack(side="left", padx=(0, 8))
        self.lo_groups_frame = ctk.CTkFrame(row3b, fg_color="transparent")
        self.lo_groups_frame.pack(fill="x", pady=(4, 0))
        self._rebuild_lo_groups_ui()

        row3c = ctk.CTkFrame(self.row3, fg_color="transparent")
        row3c.pack(fill="x", pady=2)
        ctk.CTkLabel(row3c, text="Force Cond:", width=80).pack(side="left", padx=(0, 4), anchor="n")
        ctk.CTkLabel(row3c, text="(group &, groups |)", font=("", 10), text_color="gray").pack(side="left", padx=(0, 8))
        ctk.CTkButton(row3c, text="+ Add Group", width=70, command=self._add_force_group).pack(side="left", padx=(0, 8))
        self.force_groups_frame = ctk.CTkFrame(row3c, fg_color="transparent")
        self.force_groups_frame.pack(fill="x", pady=(4, 0))
        self._rebuild_force_groups_ui()

        self.row_deb = ctk.CTkFrame(self, fg_color="transparent")
        self.row_deb.pack(fill="x", pady=2)
        self.var_deb_enable = ctk.BooleanVar(value=getattr(self.rail, "deb_enable", True))
        ctk.CTkCheckBox(self.row_deb, text="Debounce", variable=self.var_deb_enable,
                        width=90, command=self._on_deb_toggle).pack(side="left", padx=(0, 16))

        self.row_deb_params = ctk.CTkFrame(self, fg_color="transparent")
        deb_row1 = ctk.CTkFrame(self.row_deb_params, fg_color="transparent")
        deb_row1.pack(fill="x", pady=1)
        ctk.CTkLabel(deb_row1, text="CYCLE_HI:", width=80).pack(side="left", padx=(0, 4))
        self.entry_deb_cycle_hi = ctk.CTkEntry(deb_row1, width=100)
        self.entry_deb_cycle_hi.insert(0, str(getattr(self.rail, "deb_cycle_hi", 2)))
        self.entry_deb_cycle_hi.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(deb_row1, text="CYCLE_LO:", width=80).pack(side="left", padx=(0, 4))
        self.entry_deb_cycle_lo = ctk.CTkEntry(deb_row1, width=100)
        self.entry_deb_cycle_lo.insert(0, str(getattr(self.rail, "deb_cycle_lo", 2)))
        self.entry_deb_cycle_lo.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(deb_row1, text="INIT:", width=80).pack(side="left", padx=(0, 4))
        self.var_deb_init = ctk.StringVar(value="1" if getattr(self.rail, "deb_init", 0) == 1 else "0")
        ctk.CTkComboBox(deb_row1, values=["0", "1"], variable=self.var_deb_init, width=100).pack(side="left")

        deb_row2 = ctk.CTkFrame(self.row_deb_params, fg_color="transparent")
        deb_row2.pack(fill="x", pady=1)
        ctk.CTkLabel(deb_row2, text="Timing Deb:", width=80).pack(side="left", padx=(0, 4))
        deb_pulses = list(self.get_pulses()) + ["High"]
        deb_pulse_val = getattr(self.rail, "deb_pulse", "iPulse_1us") or "iPulse_1us"
        if deb_pulse_val not in deb_pulses:
            deb_pulses.append(deb_pulse_val)
        self.var_deb_pulse = ctk.StringVar(value=deb_pulse_val)
        ctk.CTkComboBox(deb_row2, values=deb_pulses, variable=self.var_deb_pulse, width=100).pack(side="left")

        self.row3.pack(fill="x", pady=2)
        self._on_type_change()

    def _get_dep_combo_values(self) -> list[str]:
        return [r.name for r in self.all_rails] + ["High", "Low"]

    def _rebuild_hi_groups_ui(self):
        for w in self.hi_groups_frame.winfo_children():
            w.destroy()
        self.hi_group_frames.clear()
        self.dep_hi_inv_vars.clear()
        self.dep_hi_use_vars.clear()
        self.dep_hi_rows.clear()
        for gi, group in enumerate(self.dep_hi_groups):
            self._add_hi_group_ui(gi)

    def _add_hi_group_ui(self, group_idx: int):
        group = self.dep_hi_groups[group_idx]
        frame = ctk.CTkFrame(self.hi_groups_frame, fg_color=("gray95", "gray20"), corner_radius=4)
        frame.pack(fill="x", pady=2, padx=(20, 0))
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=2)
        ctk.CTkLabel(header, text=f"Group {group_idx + 1}", width=50).pack(side="left", padx=(0, 8))
        combo_vals = self._get_dep_combo_values()
        combo = ctk.CTkComboBox(header, values=combo_vals, width=120)
        combo.pack(side="left", padx=(0, 8))
        if combo_vals:
            combo.set(combo_vals[0])
        ctk.CTkButton(header, text="+ Add", width=60, command=lambda: self._add_hi_cond_to_group(group_idx)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(header, text="Del Group", width=60, command=lambda: self._remove_hi_group(group_idx)).pack(side="left")
        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.hi_group_frames.append({"frame": frame, "combo": combo, "list_frame": list_frame})
        for ii, name in enumerate(group):
            self._add_hi_cond_row_to_group(group_idx, name, item_idx=ii)

    def _add_hi_cond_row_to_group(self, group_idx: int, name: str, item_idx: int | None = None):
        if item_idx is None:
            item_idx = len(self.dep_hi_groups[group_idx]) - 1
        key = (group_idx, item_idx)
        display_name = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
        is_const = name in (DEP_HIGH, DEP_LOW)
        dep_rail = self.name_to_rail.get(name)
        can_use_hi_lo = dep_rail is not None and dep_rail.has_pseqcell
        _use_display = {"self": "Node", "hi": "Hi Cond", "lo": "Lo Cond", "force": "Force Cond"}
        inv_val = False if is_const else self.rail.get_hi_inv(group_idx, item_idx, name)
        use_val = self.rail.get_hi_use(group_idx, item_idx, name)
        self.dep_hi_inv_vars[key] = ctk.BooleanVar(value=inv_val)
        self.dep_hi_use_vars[key] = ctk.StringVar(value=_use_display.get(use_val, "Node"))
        list_frame = self.hi_group_frames[group_idx]["list_frame"]
        if not list_frame.winfo_ismapped():
            list_frame.pack(fill="x", padx=4, pady=(0, 2))
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        self.dep_hi_rows[key] = row
        ctk.CTkLabel(row, text=display_name, width=100).pack(side="left", padx=(0, 4))
        if not is_const:
            ctk.CTkCheckBox(row, text="Inv", variable=self.dep_hi_inv_vars[key], width=50).pack(side="left", padx=(0, 4))
        if can_use_hi_lo:
            ctk.CTkComboBox(row, values=["Node", "Hi Cond", "Lo Cond", "Force Cond"], variable=self.dep_hi_use_vars[key], width=100).pack(side="left", padx=(0, 4))
        captured_key = key
        ctk.CTkButton(row, text="Del", width=50, command=lambda: self._remove_hi_cond_by_key(captured_key)).pack(side="left")

    def _add_hi_cond_to_group(self, group_idx: int):
        gf = self.hi_group_frames[group_idx]
        sel = gf["combo"].get()
        if not sel:
            return
        dep_key = DEP_HIGH if sel == "High" else (DEP_LOW if sel == "Low" else sel)
        self.dep_hi_groups[group_idx].append(dep_key)
        self._add_hi_cond_row_to_group(group_idx, dep_key)

    def _remove_hi_cond_by_key(self, key: tuple[int, int]):
        group_idx, item_idx = key
        if group_idx < len(self.dep_hi_groups) and item_idx < len(self.dep_hi_groups[group_idx]):
            del self.dep_hi_groups[group_idx][item_idx]
            self.dep_hi_inv_vars.pop(key, None)
            self.dep_hi_use_vars.pop(key, None)
            if key in self.dep_hi_rows:
                self.dep_hi_rows[key].destroy()
                del self.dep_hi_rows[key]
            self._rebuild_hi_groups_ui()

    def _remove_hi_group(self, group_idx: int):
        if group_idx < len(self.dep_hi_groups):
            del self.dep_hi_groups[group_idx]
            self._rebuild_hi_groups_ui()

    def _add_hi_group(self):
        self.dep_hi_groups.append([])
        self._rebuild_hi_groups_ui()

    def _rebuild_lo_groups_ui(self):
        for w in self.lo_groups_frame.winfo_children():
            w.destroy()
        self.lo_group_frames.clear()
        self.dep_lo_inv_vars.clear()
        self.dep_lo_use_vars.clear()
        self.dep_lo_rows.clear()
        for gi, group in enumerate(self.dep_lo_groups):
            self._add_lo_group_ui(gi)

    def _add_lo_group_ui(self, group_idx: int):
        group = self.dep_lo_groups[group_idx]
        frame = ctk.CTkFrame(self.lo_groups_frame, fg_color=("gray95", "gray20"), corner_radius=4)
        frame.pack(fill="x", pady=2, padx=(20, 0))
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=2)
        ctk.CTkLabel(header, text=f"Group {group_idx + 1}", width=50).pack(side="left", padx=(0, 8))
        combo_vals = self._get_dep_combo_values()
        combo = ctk.CTkComboBox(header, values=combo_vals, width=120)
        combo.pack(side="left", padx=(0, 8))
        if combo_vals:
            combo.set(combo_vals[0])
        ctk.CTkButton(header, text="+ Add", width=60, command=lambda: self._add_lo_cond_to_group(group_idx)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(header, text="Del Group", width=60, command=lambda: self._remove_lo_group(group_idx)).pack(side="left")
        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.lo_group_frames.append({"frame": frame, "combo": combo, "list_frame": list_frame})
        for ii, name in enumerate(group):
            self._add_lo_cond_row_to_group(group_idx, name, item_idx=ii)

    def _add_lo_cond_row_to_group(self, group_idx: int, name: str, item_idx: int | None = None):
        if item_idx is None:
            item_idx = len(self.dep_lo_groups[group_idx]) - 1
        key = (group_idx, item_idx)
        display_name = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
        is_const = name in (DEP_HIGH, DEP_LOW)
        dep_rail = self.name_to_rail.get(name)
        can_use_hi_lo = dep_rail is not None and dep_rail.has_pseqcell
        _use_display = {"self": "Node", "hi": "Hi Cond", "lo": "Lo Cond", "force": "Force Cond"}
        inv_val = False if is_const else self.rail.get_lo_inv(group_idx, item_idx, name)
        use_val = self.rail.get_lo_use(group_idx, item_idx, name)
        self.dep_lo_inv_vars[key] = ctk.BooleanVar(value=inv_val)
        self.dep_lo_use_vars[key] = ctk.StringVar(value=_use_display.get(use_val, "Node"))
        list_frame = self.lo_group_frames[group_idx]["list_frame"]
        if not list_frame.winfo_ismapped():
            list_frame.pack(fill="x", padx=4, pady=(0, 2))
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        self.dep_lo_rows[key] = row
        ctk.CTkLabel(row, text=display_name, width=100).pack(side="left", padx=(0, 4))
        if not is_const:
            ctk.CTkCheckBox(row, text="Inv", variable=self.dep_lo_inv_vars[key], width=50).pack(side="left", padx=(0, 4))
        if can_use_hi_lo:
            ctk.CTkComboBox(row, values=["Node", "Hi Cond", "Lo Cond", "Force Cond"], variable=self.dep_lo_use_vars[key], width=100).pack(side="left", padx=(0, 4))
        captured_key = key
        ctk.CTkButton(row, text="Del", width=50, command=lambda: self._remove_lo_cond_by_key(captured_key)).pack(side="left")

    def _add_lo_cond_to_group(self, group_idx: int):
        gf = self.lo_group_frames[group_idx]
        sel = gf["combo"].get()
        if not sel:
            return
        dep_key = DEP_HIGH if sel == "High" else (DEP_LOW if sel == "Low" else sel)
        self.dep_lo_groups[group_idx].append(dep_key)
        self._add_lo_cond_row_to_group(group_idx, dep_key)

    def _remove_lo_cond_by_key(self, key: tuple[int, int]):
        group_idx, item_idx = key
        if group_idx < len(self.dep_lo_groups) and item_idx < len(self.dep_lo_groups[group_idx]):
            del self.dep_lo_groups[group_idx][item_idx]
            self.dep_lo_inv_vars.pop(key, None)
            self.dep_lo_use_vars.pop(key, None)
            if key in self.dep_lo_rows:
                self.dep_lo_rows[key].destroy()
                del self.dep_lo_rows[key]
            self._rebuild_lo_groups_ui()

    def _remove_lo_group(self, group_idx: int):
        if group_idx < len(self.dep_lo_groups):
            del self.dep_lo_groups[group_idx]
            self._rebuild_lo_groups_ui()

    def _add_lo_group(self):
        self.dep_lo_groups.append([])
        self._rebuild_lo_groups_ui()

    def _rebuild_force_groups_ui(self):
        for w in self.force_groups_frame.winfo_children():
            w.destroy()
        self.force_group_frames.clear()
        self.dep_force_inv_vars.clear()
        self.dep_force_use_vars.clear()
        self.dep_force_rows.clear()
        for gi, group in enumerate(self.dep_force_groups):
            self._add_force_group_ui(gi)

    def _add_force_group_ui(self, group_idx: int):
        group = self.dep_force_groups[group_idx]
        frame = ctk.CTkFrame(self.force_groups_frame, fg_color=("gray95", "gray20"), corner_radius=4)
        frame.pack(fill="x", pady=2, padx=(20, 0))
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=4, pady=2)
        ctk.CTkLabel(header, text=f"Group {group_idx + 1}", width=50).pack(side="left", padx=(0, 8))
        combo_vals = self._get_dep_combo_values()
        combo = ctk.CTkComboBox(header, values=combo_vals, width=120)
        combo.pack(side="left", padx=(0, 8))
        if combo_vals:
            combo.set(combo_vals[0])
        ctk.CTkButton(header, text="+ Add", width=60, command=lambda: self._add_force_cond_to_group(group_idx)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(header, text="Del Group", width=60, command=lambda: self._remove_force_group(group_idx)).pack(side="left")
        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.force_group_frames.append({"frame": frame, "combo": combo, "list_frame": list_frame})
        for ii, name in enumerate(group):
            self._add_force_cond_row_to_group(group_idx, name, item_idx=ii)

    def _add_force_cond_row_to_group(self, group_idx: int, name: str, item_idx: int | None = None):
        if item_idx is None:
            item_idx = len(self.dep_force_groups[group_idx]) - 1
        key = (group_idx, item_idx)
        display_name = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
        is_const = name in (DEP_HIGH, DEP_LOW)
        dep_rail = self.name_to_rail.get(name)
        can_use_hi_lo = dep_rail is not None and dep_rail.has_pseqcell
        _use_display = {"self": "Node", "hi": "Hi Cond", "lo": "Lo Cond", "force": "Force Cond"}
        inv_val = False if is_const else self.rail.get_force_inv(group_idx, item_idx, name)
        use_val = self.rail.get_force_use(group_idx, item_idx, name)
        self.dep_force_inv_vars[key] = ctk.BooleanVar(value=inv_val)
        self.dep_force_use_vars[key] = ctk.StringVar(value=_use_display.get(use_val, "Node"))
        list_frame = self.force_group_frames[group_idx]["list_frame"]
        if not list_frame.winfo_ismapped():
            list_frame.pack(fill="x", padx=4, pady=(0, 2))
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        self.dep_force_rows[key] = row
        ctk.CTkLabel(row, text=display_name, width=100).pack(side="left", padx=(0, 4))
        if not is_const:
            ctk.CTkCheckBox(row, text="Inv", variable=self.dep_force_inv_vars[key], width=50).pack(side="left", padx=(0, 4))
        if can_use_hi_lo:
            ctk.CTkComboBox(row, values=["Node", "Hi Cond", "Lo Cond", "Force Cond"], variable=self.dep_force_use_vars[key], width=100).pack(side="left", padx=(0, 4))
        captured_key = key
        ctk.CTkButton(row, text="Del", width=50, command=lambda: self._remove_force_cond_by_key(captured_key)).pack(side="left")

    def _add_force_cond_to_group(self, group_idx: int):
        gf = self.force_group_frames[group_idx]
        sel = gf["combo"].get()
        if not sel:
            return
        dep_key = DEP_HIGH if sel == "High" else (DEP_LOW if sel == "Low" else sel)
        self.dep_force_groups[group_idx].append(dep_key)
        self._add_force_cond_row_to_group(group_idx, dep_key)

    def _remove_force_cond_by_key(self, key: tuple[int, int]):
        group_idx, item_idx = key
        if group_idx < len(self.dep_force_groups) and item_idx < len(self.dep_force_groups[group_idx]):
            del self.dep_force_groups[group_idx][item_idx]
            self.dep_force_inv_vars.pop(key, None)
            self.dep_force_use_vars.pop(key, None)
            if key in self.dep_force_rows:
                self.dep_force_rows[key].destroy()
                del self.dep_force_rows[key]
            self._rebuild_force_groups_ui()

    def _remove_force_group(self, group_idx: int):
        if group_idx < len(self.dep_force_groups):
            del self.dep_force_groups[group_idx]
            self._rebuild_force_groups_ui()

    def _add_force_group(self):
        self.dep_force_groups.append([])
        self._rebuild_force_groups_ui()

    def _on_apply_changes(self):
        if self.on_apply_changes:
            old_name = self.rail.name
            new_name = self.entry_name.get().strip()
            old_type = self.rail.seq_type
            new_type = self.var_type.get()
            self.on_apply_changes(old_name, new_name, old_type, new_type)

    def _on_deb_toggle(self):
        if self.var_deb_enable.get():
            self.row_deb_params.pack(fill="x", pady=2)
        else:
            self.row_deb_params.pack_forget()

    def _on_type_change(self):
        is_input = self.var_type.get() == "input"
        if is_input:
            self.row2.pack_forget()
            self.row2b.pack_forget()
            self.row3.pack_forget()
            self.row_deb.pack(fill="x", pady=2)
            self._on_deb_toggle()
            self.dep_hi_groups = [[]]
            self.dep_lo_groups = [[]]
            self.dep_force_groups = [[]]
            self.dep_hi_inv_vars.clear()
            self.dep_lo_inv_vars.clear()
            self.dep_force_inv_vars.clear()
            self.dep_hi_use_vars.clear()
            self.dep_lo_use_vars.clear()
            self.dep_force_use_vars.clear()
            self.dep_hi_rows.clear()
            self.dep_lo_rows.clear()
            self.dep_force_rows.clear()
        else:
            self.row2.pack(fill="x", pady=2)
            self.row2b.pack(fill="x", pady=2)
            self.row3.pack(fill="x", pady=2)
            self.row_deb.pack_forget()
            self.row_deb_params.pack_forget()
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
            if not self.dep_force_groups or self.dep_force_groups == [[]]:
                self.dep_force_groups = [list(g) for g in self.rail.get_force_groups()] if self.rail.get_force_groups() else [[]]
                if not self.dep_force_groups:
                    self.dep_force_groups = [[]]
                self._rebuild_force_groups_ui()

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
        groups_force = [list(g) for g in self.dep_force_groups if g]
        flat_hi = [d for g in groups_hi for d in g]
        flat_lo = [d for g in groups_lo for d in g]
        flat_force = [d for g in groups_force for d in g]
        _use_reverse = {"Node": "self", "Hi Cond": "hi", "Lo Cond": "lo", "Force Cond": "force"}
        depends_on_hi_inv = {}
        depends_on_hi_use = {}
        hi_inv_groups = []
        hi_use_groups = []
        for gi, g in enumerate(groups_hi):
            g_inv = []
            g_use = []
            for ii, n in enumerate(g):
                key = (gi, ii)
                inv = self.dep_hi_inv_vars[key].get() if key in self.dep_hi_inv_vars else False
                use = _use_reverse.get(self.dep_hi_use_vars[key].get(), "self") if key in self.dep_hi_use_vars else "self"
                depends_on_hi_inv[n] = inv
                depends_on_hi_use[n] = use
                g_inv.append(inv)
                g_use.append(use)
            hi_inv_groups.append(g_inv)
            hi_use_groups.append(g_use)
        depends_on_lo_inv = {}
        depends_on_lo_use = {}
        lo_inv_groups = []
        lo_use_groups = []
        for gi, g in enumerate(groups_lo):
            g_inv = []
            g_use = []
            for ii, n in enumerate(g):
                key = (gi, ii)
                inv = self.dep_lo_inv_vars[key].get() if key in self.dep_lo_inv_vars else False
                use = _use_reverse.get(self.dep_lo_use_vars[key].get(), "self") if key in self.dep_lo_use_vars else "self"
                depends_on_lo_inv[n] = inv
                depends_on_lo_use[n] = use
                g_inv.append(inv)
                g_use.append(use)
            lo_inv_groups.append(g_inv)
            lo_use_groups.append(g_use)
        depends_on_force_inv = {}
        depends_on_force_use = {}
        force_inv_groups = []
        force_use_groups = []
        for gi, g in enumerate(groups_force):
            g_inv = []
            g_use = []
            for ii, n in enumerate(g):
                key = (gi, ii)
                inv = self.dep_force_inv_vars[key].get() if key in self.dep_force_inv_vars else False
                use = _use_reverse.get(self.dep_force_use_vars[key].get(), "self") if key in self.dep_force_use_vars else "self"
                depends_on_force_inv[n] = inv
                depends_on_force_use[n] = use
                g_inv.append(inv)
                g_use.append(use)
            force_inv_groups.append(g_inv)
            force_use_groups.append(g_use)
        seq_type = self.var_type.get()
        if seq_type == "input":
            cycle_hi, cycle_lo = 0, 0
            groups_hi, groups_lo, groups_force = [], [], []
            flat_hi, flat_lo, flat_force = [], [], []
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
            depends_on_hi_inv_groups=hi_inv_groups if seq_type != "input" else [],
            depends_on_lo_inv_groups=lo_inv_groups if seq_type != "input" else [],
            depends_on_hi_use_groups=hi_use_groups if seq_type != "input" else [],
            depends_on_lo_use_groups=lo_use_groups if seq_type != "input" else [],
            depends_on_force=flat_force if seq_type != "input" else [],
            depends_on_force_groups=groups_force if seq_type != "input" else [],
            depends_on_force_inv=depends_on_force_inv if seq_type != "input" else {},
            depends_on_force_use=depends_on_force_use if seq_type != "input" else {},
            depends_on_force_inv_groups=force_inv_groups if seq_type != "input" else [],
            depends_on_force_use_groups=force_use_groups if seq_type != "input" else [],
            pulse_hi=self.var_pulse_hi.get() if seq_type != "input" else "iPulse_1us",
            pulse_lo=self.var_pulse_lo.get() if seq_type != "input" else "iPulse_1us",
            pulse_force=self.var_pulse_force.get() if seq_type != "input" else "iPulse_1us",
            deb_enable=self.var_deb_enable.get() if seq_type == "input" else False,
            deb_init=1 if (seq_type == "input" and self.var_deb_init.get() == "1") else 0,
            deb_cycle_hi=_safe_int(self.entry_deb_cycle_hi.get(), 2) if seq_type == "input" else 2,
            deb_cycle_lo=_safe_int(self.entry_deb_cycle_lo.get(), 2) if seq_type == "input" else 2,
            deb_cycle_sync=2,
            deb_pulse=self.var_deb_pulse.get() if seq_type == "input" else "iPulse_1us",
            cycle_hi=cycle_hi,
            cycle_lo=cycle_lo,
            cycle_force=self.rail.cycle_force,
            recover=self.rail.recover,
            init=1 if (seq_type != "input" and self.var_pseq_init.get() == "1") else 0,
            force_val=self.rail.force_val,
            cycle_sync=self.rail.cycle_sync,
            od=self.rail.od,
        )


class CollapsibleRailFrame(ctk.CTkFrame):
    """Accordion wrapper: clickable header + collapsible RailEditorFrame."""

    def __init__(self, master, rail: PowerRail, all_rails: list[PowerRail],
                 config: PowerSeqConfig, get_pulses=None, on_apply_changes=None,
                 expanded=False, **kwargs):
        super().__init__(master, **kwargs)
        self.rail = rail
        self._expanded = expanded
        # Lazy build：摺疊時不建立 RailEditorFrame，展開時才建。建構參數先存著。
        self._all_rails = all_rails
        self._config = config
        self._get_pulses = get_pulses
        self._on_apply_changes = on_apply_changes
        self.editor: RailEditorFrame | None = None

        self._header = ctk.CTkFrame(self, fg_color=("gray85", "gray25"), corner_radius=6)
        self._header.pack(fill="x")
        self._header.bind("<Button-1>", lambda _: self.toggle())

        self._arrow = ctk.CTkLabel(self._header, text="", width=20, font=("", 12))
        self._arrow.pack(side="left", padx=(8, 4))
        self._arrow.bind("<Button-1>", lambda _: self.toggle())

        type_label = SEQ_TYPE_LABELS.get(rail.seq_type, rail.seq_type)
        summary = self._build_summary(rail, type_label)
        self._title = ctk.CTkLabel(self._header, text=summary, font=("", 12, "bold"), anchor="w")
        self._title.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=6)
        self._title.bind("<Button-1>", lambda _: self.toggle())

        self._body = ctk.CTkFrame(self, fg_color="transparent")

        self._update_ui()

    def _ensure_body(self):
        if self.editor is not None:
            return
        self.editor = RailEditorFrame(
            self._body, self.rail, self._all_rails, self._config,
            get_pulses=self._get_pulses, on_apply_changes=self._on_apply_changes,
        )
        self.editor.pack(fill="x", padx=4, pady=(4, 0))

    def update_summary(self):
        type_label = SEQ_TYPE_LABELS.get(self.rail.seq_type, self.rail.seq_type)
        self._title.configure(text=self._build_summary(self.rail, type_label))

    @staticmethod
    def _build_summary(rail: PowerRail, type_label: str) -> str:
        if rail.seq_type == "input":
            if getattr(rail, "deb_enable", False):
                hi = getattr(rail, "deb_cycle_hi", 2)
                lo = getattr(rail, "deb_cycle_lo", 2)
                init_val = getattr(rail, "deb_init", 0)
                return f"{rail.name}  [{type_label}]  Deb:ON  HI:{hi}  LO:{lo}  INIT:{init_val}"
            return f"{rail.name}  [{type_label}]  Deb:OFF"
        init_val = getattr(rail, "init", 0)
        return f"{rail.name}  [{type_label}]  HI:{rail.cycle_hi}  LO:{rail.cycle_lo}  INIT:{init_val}"

    def _update_ui(self):
        self._arrow.configure(text="\u25BC" if self._expanded else "\u25B6")
        if self._expanded:
            self._ensure_body()
            self._body.pack(fill="x", pady=(0, 4))
        else:
            self._body.pack_forget()

    def toggle(self):
        self._expanded = not self._expanded
        self._update_ui()

    def expand(self):
        if not self._expanded:
            self._expanded = True
            self._update_ui()

    def collapse(self):
        if self._expanded:
            self._expanded = False
            self._update_ui()

    def get_rail(self) -> PowerRail:
        # 摺疊狀態下沒建 editor，直接回傳目前 rail（不做任何 widget 讀取）
        if self.editor is None:
            return self.rail
        return self.editor.get_rail()


class PowerSeqGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Power Sequence Config v1.1")
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
        ctk.CTkButton(toolbar, text="Export Draw.io", command=self._export_drawio, width=110).pack(side="left", padx=(0, 8))
        self._optimize_layout_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(toolbar, text="Optimize Layout", variable=self._optimize_layout_var, width=130).pack(side="left", padx=(0, 8))
        self._topmost = False
        self._pin_btn = ctk.CTkButton(toolbar, text="\U0001F4CC", width=36, command=self._toggle_topmost)
        self._pin_btn.pack(side="right")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ctk.CTkFrame(main, width=220, fg_color=("gray90", "gray17"))
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        ctk.CTkLabel(left, text="Sequence Node", font=("", 14, "bold")).pack(pady=(10, 8))
        self.rail_listbox = tk.Listbox(left, font=("Consolas", 10), selectmode="single", height=14)
        self.rail_listbox.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(left, text="Timing Signals", font=("", 12, "bold")).pack(pady=(8, 4))
        self.pulse_entry = ctk.CTkEntry(left, placeholder_text="New signal")
        self.pulse_entry.pack(fill="x", pady=(0, 4))
        self.pulse_listbox = tk.Listbox(left, font=("Consolas", 9), selectmode="single", height=4)
        self.pulse_listbox.pack(fill="x", pady=(0, 4))
        pulse_btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        pulse_btn_frame.pack(fill="x", pady=(0, 8))
        pulse_btn_frame.columnconfigure(0, weight=1)
        pulse_btn_frame.columnconfigure(1, weight=1)
        ctk.CTkButton(pulse_btn_frame, text="+ Add", command=self._add_pulse).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ctk.CTkButton(pulse_btn_frame, text="- Delete", command=self._delete_pulse).grid(row=0, column=1, sticky="ew", padx=(2, 0))
        self.rail_listbox.bind("<<ListboxSelect>>", self._on_rail_select)
        self._drag_start_index = None
        self._drag_current_index = None
        self.rail_listbox.bind("<ButtonPress-1>", self._on_listbox_press)
        self.rail_listbox.bind("<B1-Motion>", self._on_listbox_motion)
        self.rail_listbox.bind("<ButtonRelease-1>", self._on_listbox_release)
        self._refresh_pulse_listbox()

        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        self.editor_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.editor_scroll.pack(fill="both", expand=True)
        self.collapsible_frames: list[CollapsibleRailFrame] = []
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
        prev_expanded = set()
        for cf in getattr(self, "collapsible_frames", []):
            if cf._expanded:
                prev_expanded.add(cf.rail.name)

        for w in self.editor_scroll.winfo_children():
            w.destroy()
        self.collapsible_frames = []
        def get_pulses():
            return getattr(self.config, "pulses", None) or ["iPulse_1us"]
        for r in self.config.rails:
            is_expanded = r.name in prev_expanded if prev_expanded else False
            cf = CollapsibleRailFrame(
                self.editor_scroll, r, self.config.rails, self.config,
                get_pulses=get_pulses, on_apply_changes=self._apply_changes,
                expanded=is_expanded,
            )
            cf.pack(fill="x", pady=4, padx=4)
            self.collapsible_frames.append(cf)
        self.rail_listbox.delete(0, tk.END)
        for r in self.config.rails:
            t = SEQ_TYPE_LABELS.get(r.seq_type, r.seq_type)[:16]
            label = f"{r.name} [{t}]"
            self.rail_listbox.insert(tk.END, label)

    def _on_rail_select(self, event):
        sel = self.rail_listbox.curselection()
        if not sel or sel[0] >= len(self.collapsible_frames):
            return
        idx = sel[0]
        cf = self.collapsible_frames[idx]
        cf.expand()
        self.after(50, lambda: cf.winfo_toplevel().update_idletasks())
        self.after(100, lambda: self._scroll_to_widget(cf))

    def _scroll_to_widget(self, widget):
        canvas = self.editor_scroll._parent_canvas
        canvas.update_idletasks()
        try:
            widget_y = widget.winfo_y()
            scroll_height = canvas.winfo_height()
            canvas_scroll_region = canvas.bbox("all")
            if canvas_scroll_region is None:
                return
            total_height = canvas_scroll_region[3]
            if total_height <= scroll_height:
                return
            target = max(0.0, min(1.0, widget_y / total_height))
            canvas.yview_moveto(target)
        except Exception:
            pass

    def _on_listbox_press(self, event):
        idx = self.rail_listbox.nearest(event.y)
        if 0 <= idx < self.rail_listbox.size():
            self._drag_start_index = idx
            self._drag_current_index = idx

    def _on_listbox_motion(self, event):
        if self._drag_start_index is None:
            return
        new_pos = self.rail_listbox.nearest(event.y)
        if new_pos < 0 or new_pos >= self.rail_listbox.size():
            return
        if new_pos == self._drag_current_index:
            return
        # 即時更新 listbox 顯示，讓拖拉時能看到節點移動
        label = self.rail_listbox.get(self._drag_current_index)
        self.rail_listbox.delete(self._drag_current_index)
        # 刪除後列表變短，new_pos 仍對應目標視覺位置
        insert_pos = new_pos
        self.rail_listbox.insert(insert_pos, label)
        self.rail_listbox.selection_clear(0, tk.END)
        self.rail_listbox.selection_set(insert_pos)
        self.rail_listbox.see(insert_pos)
        self._drag_current_index = insert_pos

    def _on_listbox_release(self, event):
        start_idx = self._drag_start_index
        end_idx = self._drag_current_index
        self._drag_start_index = None
        self._drag_current_index = None
        if start_idx is None:
            return
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
        self.collapsible_frames[-1].expand()
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
            rails=[cf.get_rail() for cf in self.collapsible_frames],
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
        if target_idx is None:
            return

        applied_rail = self.collapsible_frames[target_idx].get_rail()
        self.config.rails[target_idx] = applied_rail

        name_or_type_changed = (new_name != old_name) or (new_type != old_type)
        if name_or_type_changed:
            # 改名或改類型：其他節點的依賴下拉選項都會變，必須全量重建
            for r in self.config.rails:
                r.depends_on_hi = [new_name if n == old_name else n for n in r.depends_on_hi]
                r.depends_on_lo = [new_name if n == old_name else n for n in r.depends_on_lo]
                r.depends_on_force = [new_name if n == old_name else n for n in r.depends_on_force]
                r.depends_on_hi_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_hi_groups]
                r.depends_on_lo_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_lo_groups]
                r.depends_on_force_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_force_groups]
                r.depends_on_hi_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_hi_inv.items()}
                r.depends_on_lo_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_lo_inv.items()}
                r.depends_on_force_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_force_inv.items()}
                r.depends_on_hi_use = {new_name if k == old_name else k: v for k, v in r.depends_on_hi_use.items()}
                r.depends_on_lo_use = {new_name if k == old_name else k: v for k, v in r.depends_on_lo_use.items()}
                r.depends_on_force_use = {new_name if k == old_name else k: v for k, v in r.depends_on_force_use.items()}
            self._refresh_editors()
        else:
            # 只改了自己節點屬性（cycle/dep/timing/...）：僅更新自己的 summary 與背景 rail，
            # 不動其他節點的 widget
            cf = self.collapsible_frames[target_idx]
            cf.rail = applied_rail
            if cf.editor is not None:
                cf.editor.rail = applied_rail
            cf.update_summary()

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

    def _export_drawio(self):
        config = self._collect_config()
        if not config.rails:
            messagebox.showinfo("Notice", "No nodes. Add rails first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xml",
            filetypes=[("XML", "*.xml"), ("All", "*")]
        )
        if path:
            try:
                xml = generate_drawio(config, optimize_layout=self._optimize_layout_var.get())
                open(path, "w", encoding="utf-8").write(xml)
                messagebox.showinfo("Saved", f"Saved: {path}\nOpen in Draw.io (diagrams.net) to view.")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _toggle_topmost(self):
        self._topmost = not self._topmost
        self.attributes("-topmost", self._topmost)
        self._pin_btn.configure(fg_color=("green", "#2a8c2a") if self._topmost else ctk.ThemeManager.theme["CTkButton"]["fg_color"])

def run_gui():
    app = PowerSeqGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
