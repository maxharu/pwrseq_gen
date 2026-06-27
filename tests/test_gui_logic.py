"""Tests for GUI pure logic extracted from PowerSeqGUI."""
import os

from snapshot_history import SnapshotHistory


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
