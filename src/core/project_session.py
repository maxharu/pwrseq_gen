"""文件層的狀態與政策：config / path / dirty / saving / undo-redo / 標題合成。

從 `PowerSeqGUI` 抽出，讓會造成「使用者工作遺失」的那類邏輯——存檔後 dirty 有沒有消、
undo 回到存檔點後 dirty 對不對、存檔途中重入——不需要 Tk 就能測。純資料與政策，不碰 widget。

`core/snapshot_history.py` 管的是 undo/redo 的**機制**；這裡管的是**政策**：什麼算存檔點、
undo 回到存檔點後 dirty 該不該消、存檔中能不能再存。`recent` 以依賴注入傳入（只需要
`.add(path)`），所以 core 不反向依賴 gui。
"""
from __future__ import annotations

import json

from core.config_models import PowerSeqConfig
from core.snapshot_history import SnapshotHistory


def _snapshot(config: PowerSeqConfig) -> str:
    return json.dumps(config.to_dict(), ensure_ascii=False)


class _NullRecent:
    """沒注入 recent 時的安靜替身（測試用）。"""

    def add(self, path: str) -> None:
        pass


class ProjectSession:
    """一份正在編輯的專案：內容、路徑、未存旗標、undo/redo、存檔點。"""

    def __init__(self, *, base_title: str, undo_limit: int, recent=None):
        self.config = PowerSeqConfig()
        self.path: str | None = None
        self.saving = False
        self._base_title = base_title
        self._history = SnapshotHistory(undo_limit)
        self.recent = recent if recent is not None else _NullRecent()
        self._dirty = False
        self._saved_snapshot = _snapshot(self.config)

    # ---- queries ----
    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def can_undo(self) -> bool:
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._history.can_redo

    def title(self) -> str:
        return self._base_title + (" *" if self._dirty else "")

    # ---- editing ----
    def mark_edited(self) -> None:
        self._dirty = True

    def push_undo(self, current: PowerSeqConfig) -> None:
        """在一次編輯**之前**記錄目前狀態。不碰 dirty——那是 `mark_edited` 的事。"""
        self._history.push(_snapshot(current))

    def undo(self, current: PowerSeqConfig) -> bool:
        """回上一步；沒東西可回時回 False、不動任何狀態。"""
        return self._restore(self._history.undo(_snapshot(current)))

    def redo(self, current: PowerSeqConfig) -> bool:
        return self._restore(self._history.redo(_snapshot(current)))

    def _restore(self, snapshot: str | None) -> bool:
        if snapshot is None:
            return False
        self.config = PowerSeqConfig.from_dict(json.loads(snapshot))
        # 回到存檔點就不該還顯示未存：dirty = 還原到的內容是否偏離上次存檔的快照。
        self._dirty = snapshot != self._saved_snapshot
        return True

    # ---- saved point ----
    def set_saved_point(self, displayed: PowerSeqConfig) -> None:
        """把「目前顯示的內容」定為存檔點：清 dirty，並記住快照供 undo/redo 比對。

        之所以吃「目前顯示的內容」而非剛讀進來的 config，是因為 GUI 的 `_collect_config`
        會正規化（補 pulses 預設、依狀況清空 timing_scenario）；undo 比對的也是這個正規化
        後的形式，兩邊要用同一把尺，存檔點才錨得準。
        """
        self._saved_snapshot = _snapshot(displayed)
        self._dirty = False

    # ---- open / save ----
    def load(self, path: str, config: PowerSeqConfig) -> None:
        self.config = config
        self.path = path
        self._history.clear()
        self.recent.add(path)
        self.set_saved_point(config)

    def begin_save(self) -> bool:
        """開始存檔；已在存檔中則回 False（擋重入，避免兩條緒同時寫同一個檔）。"""
        if self.saving:
            return False
        self.saving = True
        return True

    def finish_save(self, path: str, config: PowerSeqConfig) -> None:
        self.saving = False
        self.config = config
        self.path = path
        self.recent.add(path)
        self.set_saved_point(config)

    def fail_save(self) -> None:
        self.saving = False
