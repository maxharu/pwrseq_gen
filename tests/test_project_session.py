"""ProjectSession：文件狀態與政策，不需要 Tk。

守的是會造成「使用者工作遺失」的那類交互——存檔後 dirty 要消、undo 回到存檔點後
dirty 不該還亮著、存檔途中不得重入。這些以前綁在 Tk 上，一行測試都沒有。
"""
from __future__ import annotations

from core.config_models import PowerRail, PowerSeqConfig
from core.project_session import ProjectSession


def _cfg(name: str) -> PowerSeqConfig:
    return PowerSeqConfig(
        rails=[PowerRail(name, seq_type="input", cycle_hi=1, cycle_lo=1)]
    )


def _names(session: ProjectSession) -> list[str]:
    return [r.name for r in session.config.rails]


class _FakeRecent:
    def __init__(self):
        self.added: list[str] = []

    def add(self, path: str) -> None:
        self.added.append(path)


def _session(recent=None) -> ProjectSession:
    return ProjectSession(base_title="App 1.0", undo_limit=10, recent=recent)


# ---- 初始狀態 / 標題 -------------------------------------------------------

def test_fresh_session_is_clean_with_no_history():
    s = _session()
    assert not s.is_dirty
    assert s.path is None
    assert not s.can_undo and not s.can_redo
    assert s.title() == "App 1.0"


def test_title_shows_star_only_when_dirty():
    s = _session()
    s.mark_edited()
    assert s.is_dirty
    assert s.title() == "App 1.0 *"


# ---- open --------------------------------------------------------------

def test_load_sets_path_clears_dirty_and_history_and_records_recent():
    recent = _FakeRecent()
    s = _session(recent)
    s.mark_edited()
    s.push_undo(_cfg("OLD"))

    s.load("proj.json", _cfg("A"))

    assert s.path == "proj.json"
    assert not s.is_dirty
    assert not s.can_undo and not s.can_redo  # 開新檔清掉舊歷史
    assert _names(s) == ["A"]
    assert recent.added == ["proj.json"]


# ---- undo / redo × dirty（核心） ------------------------------------------

def test_undo_back_to_saved_point_clears_dirty():
    """A→B→C 後連退兩步回到剛載入(=存檔點)的 A，dirty 必須消。這就是修正的那條。"""
    s = _session()
    s.load("p.json", _cfg("A"))

    s.push_undo(_cfg("A"))          # 編輯 A→B 前先記錄
    s.config = _cfg("B")
    s.mark_edited()
    s.push_undo(_cfg("B"))          # 編輯 B→C 前先記錄
    s.config = _cfg("C")
    s.mark_edited()
    assert s.is_dirty

    assert s.undo(_cfg("C")) is True   # 回到 B：偏離存檔點
    assert _names(s) == ["B"]
    assert s.is_dirty

    assert s.undo(_cfg("B")) is True   # 回到 A：等於存檔點
    assert _names(s) == ["A"]
    assert not s.is_dirty              # ← 修正：不再無條件 dirty


def test_redo_away_from_saved_point_sets_dirty():
    s = _session()
    s.load("p.json", _cfg("A"))
    s.push_undo(_cfg("A"))
    s.config = _cfg("B")
    s.mark_edited()
    s.undo(_cfg("B"))
    assert _names(s) == ["A"] and not s.is_dirty

    assert s.redo(_cfg("A")) is True
    assert _names(s) == ["B"]
    assert s.is_dirty


def test_undo_with_empty_history_is_a_noop():
    s = _session()
    s.load("p.json", _cfg("A"))
    assert s.undo(_cfg("A")) is False
    assert _names(s) == ["A"]
    assert not s.is_dirty


def test_saved_point_follows_the_latest_save_not_the_original_load():
    """存檔後，存檔點移到新內容；undo 回到舊的『已載入』狀態反而算 dirty。"""
    s = _session()
    s.load("p.json", _cfg("A"))
    s.push_undo(_cfg("A"))
    s.config = _cfg("B")
    s.mark_edited()
    s.finish_save("p.json", _cfg("B"))   # 存檔點 = B
    assert not s.is_dirty

    assert s.undo(_cfg("B")) is True      # 回到 A
    assert _names(s) == ["A"]
    assert s.is_dirty                     # A 已不是存檔點


# ---- save：清 dirty + 擋重入 ----------------------------------------------

def test_finish_save_clears_dirty_and_sets_path_and_recent():
    recent = _FakeRecent()
    s = _session(recent)
    s.mark_edited()
    assert s.is_dirty

    s.finish_save("out.json", _cfg("A"))

    assert not s.is_dirty
    assert s.path == "out.json"
    assert recent.added == ["out.json"]


def test_begin_save_blocks_reentrancy_until_finished():
    s = _session()
    assert s.begin_save() is True
    assert s.begin_save() is False       # 存檔中不得再存
    s.finish_save("out.json", _cfg("A"))
    assert s.begin_save() is True         # 存完又能存


def test_failed_save_releases_the_lock_and_keeps_dirty():
    s = _session()
    s.mark_edited()
    assert s.begin_save() is True
    s.fail_save()
    assert s.begin_save() is True         # 失敗後能重試
    assert s.is_dirty                     # 存檔沒成功，未存狀態保留


def test_set_saved_point_anchors_dirty_to_displayed_content():
    s = _session()
    s.mark_edited()
    s.set_saved_point(_cfg("A"))
    assert not s.is_dirty
