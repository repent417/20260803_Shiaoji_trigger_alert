"""
Storage Manager Module
負責任選觸價單條件資料的本地端 JSON 讀取與存檔。
"""
import os
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def sanitize_filename(filepath: str, max_length: int = 70) -> str:
    """限制檔名 (包含副檔名) 最大長度不超過 max_length (預設 70 個字)"""
    dirname, filename = os.path.split(filepath)
    name, ext = os.path.splitext(filename)
    max_name_len = max_length - len(ext)
    if max_name_len > 0 and len(name) > max_name_len:
        filename = name[:max_name_len] + ext
    return os.path.join(dirname, filename) if dirname else filename

class StorageManager:
    def __init__(self, filepath: str = os.path.join("data", "alert_rules.json")):
        self.filepath = sanitize_filename(filepath, 70)
        self._ensure_dir()

    def _ensure_dir(self):
        """確保儲存目錄存在"""
        dirname = os.path.dirname(self.filepath)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)

    def load_rules(self) -> List[Dict[str, Any]]:
        """載入所有觸價設定"""
        if not os.path.exists(self.filepath):
            logger.info(f"觸價規則檔不存在 ({self.filepath})，將回傳空選單")
            return []

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                logger.warning("觸價規則檔格式不正確，應為列表。")
                return []
        except Exception as e:
            logger.error(f"讀取觸價規則檔失敗: {e}")
            return []

    def save_rules(self, rules: List[Dict[str, Any]]) -> bool:
        """儲存所有觸價設定至 JSON 檔案"""
        try:
            self._ensure_dir()
            temp_file = self.filepath + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(rules, f, ensure_ascii=False, indent=2)
            
            # 原子替換
            if os.path.exists(self.filepath):
                os.remove(self.filepath)
            os.rename(temp_file, self.filepath)
            logger.info(f"成功儲存 {len(rules)} 條觸價規則至 {self.filepath}")
            return True
        except Exception as e:
            logger.error(f"儲存觸價規則檔失敗: {e}")
            return False
