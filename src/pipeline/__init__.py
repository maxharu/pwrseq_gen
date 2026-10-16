"""應用服務層：把各匯出格式的「驗證 → 產生 → 寫檔」收成一個不綁 UI 的呼叫點。"""
from pipeline.export import ExportResult, export

__all__ = ["ExportResult", "export"]
