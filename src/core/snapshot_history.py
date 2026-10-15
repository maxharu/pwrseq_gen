"""Undo/redo snapshot stacks — pure logic, no GUI dependency.

從 PowerSeqGUI 抽出，方便獨立測試。快照本身是 config 的 JSON 字串，
此類別僅管理兩個有界堆疊與 push/undo/redo 語意。
"""


class SnapshotHistory:
    """雙堆疊 undo/redo：undo 堆疊有界（limit），push 會清空 redo。"""

    def __init__(self, limit: int):
        self._limit = limit
        self._undo: list[str] = []
        self._redo: list[str] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def push(self, snapshot: str) -> None:
        """記錄一個新狀態：壓入 undo（超過上限丟最舊）並清空 redo。"""
        self._undo.append(snapshot)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current: str) -> str | None:
        """回上一步：把 current 推入 redo，回傳要還原的快照；無可還原則回 None。"""
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current: str) -> str | None:
        """重做：把 current 推入 undo（有界），回傳要還原的快照；無則回 None。"""
        if not self._redo:
            return None
        self._undo.append(current)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        return self._redo.pop()
