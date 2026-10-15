"""Tests for GUI pure logic extracted from PowerSeqGUI."""
import os

import pytest

from core.snapshot_history import SnapshotHistory


class TestWriteConfigFile:
    def test_json_write_roundtrip(self, tmp_path):
        import json

        pytest.importorskip("customtkinter")
        from core.config_models import PowerRail, PowerSeqConfig
        from gui.app import _write_config_file

        cfg = PowerSeqConfig(rails=[PowerRail("A", seq_type="input")])
        path = tmp_path / "out.json"
        _write_config_file(cfg, str(path))

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["rails"][0]["name"] == "A"


class TestCondSectionModelWiring:
    """CondSectionFrame 與 CondEditModel 之間的接線。

    `tests/test_cond_edit.py` 證明模型的索引算術是對的；這裡證明 widget 真的照模型走：
    結構操作有改到模型、重繪後的 Tk 變數與模型一致、使用者改 Tk 變數有寫回模型。
    模型對但接線錯的話，前者會全綠而 GUI 照樣壞掉。
    """

    GROUPS = [["SIG_1", "SIG_2", "SIG_3"], ["SIG_4", "SIG_5"], ["SIG_6"]]
    INV = [[True, False, True], [False, True], [True]]
    USE = [["hi", "self", "lo"], ["force", "hi"], ["self"]]

    @pytest.fixture
    def section(self, ctk_root):
        from core.cond_edit import CondEditModel
        from gui.widgets import CondSectionFrame

        names = [n for g in self.GROUPS for n in g]
        sec = CondSectionFrame(
            ctk_root,
            kind="hi",
            get_dep_options=lambda: names + ["High", "Low"],
            is_pseqcell_for=lambda _n: True,
            model=CondEditModel(
                groups=[list(g) for g in self.GROUPS],
                inv=[list(x) for x in self.INV],
                use=[list(x) for x in self.USE],
                group_inv=[True, False, True],
                group_intra_op=["and", "or", "xor"],
            ),
        )
        try:
            yield sec
        finally:
            sec.destroy()

    @staticmethod
    def _assert_vars_match_model(sec):
        """重繪後，每一列的 Tk 變數都必須等於模型裡對應的值。"""
        from gui.theme import USE_REVERSE

        for gi, g in enumerate(sec.model.groups):
            for ii in range(len(g)):
                assert (gi, ii) in sec.inv_vars, f"({gi},{ii}) 少了 inv 變數"
                assert bool(sec.inv_vars[(gi, ii)].get()) == sec.model.inv[gi][ii]
                assert USE_REVERSE.get(sec.use_vars[(gi, ii)].get(), "self") == \
                    sec.model.use[gi][ii]
        extra = [k for k in sec.inv_vars if k[0] >= len(sec.model.groups)
                 or k[1] >= len(sec.model.groups[k[0]])]
        assert not extra, f"重繪後留下了過期的變數：{extra}"

    def test_initial_render_matches_the_model(self, section):
        assert section.get_groups() == self.GROUPS
        assert section.get_inv_groups() == self.INV
        assert section.get_use_groups() == self.USE
        self._assert_vars_match_model(section)

    def test_removing_a_group_rebuilds_consistently(self, section):
        section._remove_group(1)
        assert section.get_groups() == [self.GROUPS[0], self.GROUPS[2]]
        assert section.get_inv_groups() == [self.INV[0], self.INV[2]]
        assert section.get_use_groups() == [self.USE[0], self.USE[2]]
        assert section.get_group_intra_op() == ["and", "xor"]
        self._assert_vars_match_model(section)

    def test_reordering_groups_rebuilds_consistently(self, section):
        section._reorder_groups(0, 2)
        assert section.get_groups() == [self.GROUPS[1], self.GROUPS[2], self.GROUPS[0]]
        assert section.get_use_groups() == [self.USE[1], self.USE[2], self.USE[0]]
        assert section.get_group_intra_op() == ["or", "xor", "and"]
        self._assert_vars_match_model(section)

    def test_removing_a_dependency_rebuilds_consistently(self, section):
        section._remove_cond_by_key((0, 1))
        assert section.get_groups()[0] == ["SIG_1", "SIG_3"]
        assert section.get_inv_groups()[0] == [True, True]
        assert section.get_use_groups()[0] == ["hi", "lo"]
        self._assert_vars_match_model(section)

    def test_reordering_dependencies_rebuilds_consistently(self, section):
        section._reorder_cond(0, 0, 2)
        assert section.get_groups()[0] == ["SIG_2", "SIG_3", "SIG_1"]
        assert section.get_inv_groups()[0] == [False, True, True]
        assert section.get_use_groups()[0] == ["self", "lo", "hi"]
        self._assert_vars_match_model(section)

    def test_editing_a_tk_var_writes_back_to_the_model(self, section):
        """使用者勾 Inv / 改 Use 必須寫回模型，否則下一次重繪就會弄丟。"""
        from gui.theme import USE_LABELS

        section.inv_vars[(0, 1)].set(True)
        assert section.model.inv[0][1] is True
        assert section.get_inv_groups()[0] == [True, True, True]

        section.use_vars[(0, 1)].set(USE_LABELS["force"])
        assert section.model.use[0][1] == "force"
        assert section.get_use_groups()[0] == ["hi", "force", "lo"]

    def test_edits_survive_a_structural_change(self, section):
        """這是整個重構的核心：inv/use 不再只存在 Tk 變數裡，所以重繪不會弄丟編輯。

        改版前 `_rebuild_groups_ui` 會把 inv/use 重設回載入時的值，正因如此才需要
        那 210 行外科手術式的重映射。
        """
        section.inv_vars[(2, 0)].set(False)
        section._remove_group(0)
        assert section.get_groups() == [self.GROUPS[1], self.GROUPS[2]]
        assert section.get_inv_groups()[1] == [False], "SIG_6 的編輯在刪除後被還原了"

    def test_self_reference_coerces_use_and_writes_it_back(self, ctk_root):
        """節點在自己的 Hi 段引用自己時，`use` 不能是 Node／Hi Cond（會變成組合迴圈）。

        被限縮後的值必須寫回 model，否則下一次重繪又會跳回設定檔裡的原值。
        """
        from core.cond_edit import CondEditModel
        from gui.theme import USE_LABELS
        from gui.widgets import CondSectionFrame

        sec = CondSectionFrame(
            ctk_root,
            kind="hi",
            get_dep_options=lambda: ["ME"],
            is_pseqcell_for=lambda _n: True,
            get_self_name=lambda: "ME",
            model=CondEditModel(groups=[["ME"]], use=[["self"]]),
        )
        try:
            assert sec.model.use[0][0] != "self", "自我參照的 use 沒有被限縮"
            assert sec.model.use[0][0] == "lo", "Node 與 Hi Cond 被排除後應落到 Lo Cond"
            assert sec.use_vars[(0, 0)].get() == USE_LABELS["lo"]
            assert sec.get_use_groups() == [["lo"]]
        finally:
            sec.destroy()

    def test_adding_a_group_then_a_dependency(self, section):
        section.add_group()
        assert len(section.model.groups) == 4
        section.group_frames[3]["combo"].set("SIG_1")
        section._add_cond_to_group(3)
        assert section.model.groups[3] == ["SIG_1"]
        self._assert_vars_match_model(section)


class TestCondDepOptionsRefresh:
    def test_refresh_updates_combo_values_after_rename(self, ctk_root):
        from core.cond_edit import CondEditModel
        from gui.widgets import CondSectionFrame

        names = ["SIG_1", "SIG_2"]

        def get_opts():
            return list(names) + ["High", "Low"]

        try:
            sec = CondSectionFrame(
                ctk_root,
                kind="hi",
                get_dep_options=get_opts,
                is_pseqcell_for=lambda _n: True,
                model=CondEditModel(),
            )
            combo = sec.group_frames[0]["combo"]
            assert "SIG_1" in combo.cget("values")
            assert "RENAMED" not in combo.cget("values")

            names[0] = "RENAMED"
            sec.refresh_dep_options()
            vals = list(combo.cget("values"))
            assert "RENAMED" in vals
            assert "SIG_1" not in vals
            assert vals[-2:] == ["High", "Low"]
        finally:
            sec.destroy()


class TestSnapshotHistory:
    def test_empty(self):
        h = SnapshotHistory(limit=3)
        assert not h.can_undo
        assert not h.can_redo
        assert h.undo("cur") is None
        assert h.redo("cur") is None

    def test_push_enables_undo_and_clears_redo(self):
        h = SnapshotHistory(limit=3)
        h.push("a")
        assert h.can_undo
        # 製造 redo
        assert h.undo("b") == "a"
        assert h.can_redo
        # push 應清空 redo
        h.push("c")
        assert not h.can_redo

    def test_undo_redo_round_trip(self):
        h = SnapshotHistory(limit=5)
        h.push("s1")
        target = h.undo("cur")
        assert target == "s1"
        assert not h.can_undo
        # redo 還原 current
        back = h.redo("s1")
        assert back == "cur"
        assert h.can_undo
        assert not h.can_redo

    def test_undo_bounded(self):
        h = SnapshotHistory(limit=2)
        h.push("a")
        h.push("b")
        h.push("c")  # a 被丟棄
        assert h.undo("d") == "c"
        assert h.undo("e") == "b"
        assert h.undo("f") is None  # a 已不在

    def test_clear(self):
        h = SnapshotHistory(limit=3)
        h.push("a")
        h.undo("b")
        h.clear()
        assert not h.can_undo
        assert not h.can_redo


class TestGuiSettings:
    def test_default_and_persist(self, tmp_path):
        from gui.settings import GuiSettings
        from gui.theme import PREVIEW_FONT_SIZE_DEFAULT

        s = GuiSettings(base_dir=str(tmp_path))
        assert s.get_preview_font_size() == PREVIEW_FONT_SIZE_DEFAULT

        s.set_preview_font_size(16)
        reloaded = GuiSettings(base_dir=str(tmp_path))
        assert reloaded.get_preview_font_size() == 16

    def test_invalid_size_ignored(self, tmp_path):
        from gui.settings import GuiSettings

        s = GuiSettings(base_dir=str(tmp_path))
        s.set_preview_font_size(14)
        s.set_preview_font_size(9999)  # 不在合法清單
        assert s.get_preview_font_size() == 14


class TestRecentFiles:
    def test_add_dedup_and_order(self, tmp_path):
        from gui.settings import RecentFiles

        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text("{}", encoding="utf-8")
        f2.write_text("{}", encoding="utf-8")

        r = RecentFiles(base_dir=str(tmp_path))
        r.add(str(f1))
        r.add(str(f2))
        assert r.list()[0] == os.path.abspath(str(f2))

        r.add(str(f1))  # 重複 → 移到最前
        assert r.list()[0] == os.path.abspath(str(f1))
        assert len(r.list()) == 2

    def test_max_cap_and_reload_existing(self, tmp_path):
        from gui.settings import RecentFiles

        paths = []
        for i in range(RecentFiles.MAX + 3):
            p = tmp_path / f"f{i}.json"
            p.write_text("{}", encoding="utf-8")
            paths.append(str(p))

        r = RecentFiles(base_dir=str(tmp_path))
        for p in paths:
            r.add(p)
        assert len(r.list()) == RecentFiles.MAX

        reloaded = RecentFiles(base_dir=str(tmp_path))
        assert len(reloaded.list()) == RecentFiles.MAX
