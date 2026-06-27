"""GUI persistence: user preferences and recent-files list."""
import json
import os

from applog import get_logger
from gui.theme import _PWRSEQ_USER_DIR, PREVIEW_FONT_SIZE_DEFAULT, PREVIEW_FONT_SIZES

logger = get_logger(__name__)


class GuiSettings:
    """GUI 偏好設定，儲存於 ~/.pwrseq_gen/gui_settings.json。"""

    def __init__(self, base_dir: str | None = None):
        self._dir = base_dir or _PWRSEQ_USER_DIR
        self._path = os.path.join(self._dir, "gui_settings.json")
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            logger.debug("讀取 GUI 設定失敗：%s", self._path, exc_info=True)
            return {}

    def _save(self) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.warning("寫入 GUI 設定失敗：%s", self._path, exc_info=True)

    def get_preview_font_size(self) -> int:
        try:
            size = int(self._data.get("preview_font_size", PREVIEW_FONT_SIZE_DEFAULT))
        except (TypeError, ValueError):
            return PREVIEW_FONT_SIZE_DEFAULT
        return size if size in PREVIEW_FONT_SIZES else PREVIEW_FONT_SIZE_DEFAULT

    def set_preview_font_size(self, size: int) -> None:
        if size not in PREVIEW_FONT_SIZES:
            return
        self._data["preview_font_size"] = size
        self._save()


class RecentFiles:
    """Recent files 儲存於 ~/.pwrseq_gen/recent.json，最多 8 個。"""

    MAX = 8

    def __init__(self, base_dir: str | None = None):
        self._dir = base_dir or _PWRSEQ_USER_DIR
        self._path = os.path.join(self._dir, "recent.json")
        self._items: list[str] = self._load()

    def _load(self) -> list[str]:
        try:
            with open(self._path, encoding="utf-8") as f:
                items = json.load(f)
            return [p for p in items if isinstance(p, str) and os.path.isfile(p)][: self.MAX]
        except FileNotFoundError:
            return []
        except Exception:
            logger.debug("讀取 recent 檔案失敗：%s", self._path, exc_info=True)
            return []

    def _save(self) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.warning("寫入 recent 檔案失敗：%s", self._path, exc_info=True)

    def add(self, path: str) -> None:
        if not path:
            return
        path = os.path.abspath(path)
        if path in self._items:
            self._items.remove(path)
        self._items.insert(0, path)
        self._items = self._items[: self.MAX]
        self._save()

    def list(self) -> list[str]:
        return list(self._items)
