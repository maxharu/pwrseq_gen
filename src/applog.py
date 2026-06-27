"""Application logging setup.

集中設定 logging：輸出到 stderr 與 ~/.pwrseq_gen/pwrseq_gen.log（rotating）。
在進入點呼叫一次 setup_logging()；各模組以 get_logger(__name__) 取得 logger。
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.expanduser("~"), ".pwrseq_gen")
_LOG_FILE = os.path.join(_LOG_DIR, "pwrseq_gen.log")
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """設定 root logger（idempotent）。檔案無法寫入時退回僅 stderr。"""
    global _configured
    if _configured:
        return

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                _LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8",
            )
        )
    except OSError:
        pass

    logging.basicConfig(level=level, format=_FORMAT, handlers=handlers)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
