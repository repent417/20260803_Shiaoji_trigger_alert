"""
Notification Engine Module
提供三重通知機制：Windows 桌面彈窗 (Toast)、系統音效 (Audio Beep)、Telegram Bot 訊息推播。
"""
import os
import sys
import threading
import logging
import requests
from datetime import datetime
from typing import Dict, Any, List, Callable, Optional

logger = logging.getLogger(__name__)

# 嘗試載入 plyer 桌面通知庫
try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False

# 嘗試載入 winsound 音效庫 (Windows 專用)
try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False


class Notifier:
    def __init__(self, telegram_token: str = "", telegram_chat_id: str = ""):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.logs: List[Dict[str, Any]] = []
        self.log_callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def set_telegram_config(self, token: str, chat_id: str):
        """更新 Telegram Bot 設定"""
        self.telegram_token = token
        self.telegram_chat_id = chat_id

    def add_log_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """註冊 GUI 通知紀錄變更回呼"""
        self.log_callbacks.append(callback)

    def notify(self, title: str, message: str, stock_code: str = "", trigger_type: str = ""):
        """
        發送多重觸價通知
        :param title: 通知標題 (例: "股價觸價警示 [2330 台積電]")
        :param message: 通知詳細內容 (例: "成交價 860 已突破設定上界 850！")
        :param stock_code: 股票代號
        :param trigger_type: UPPER (突破) / LOWER (跌破)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "title": title,
            "message": message,
            "stock_code": stock_code,
            "trigger_type": trigger_type,
            "telegram_sent": False
        }

        # 1. 紀錄至本機 Log 列表
        self.logs.append(log_entry)
        for cb in self.log_callbacks:
            try:
                cb(log_entry)
            except Exception as e:
                logger.error(f"Log callback 執行失敗: {e}")

        # 2. 異步執行聲音與 Toast 彈窗 (避免阻塞主執行緒)
        threading.Thread(target=self._play_sound, daemon=True).start()
        threading.Thread(target=self._show_toast, args=(title, message), daemon=True).start()

        # 3. 異步發送 Telegram 訊息
        if self.telegram_token and self.telegram_chat_id:
            threading.Thread(target=self._send_telegram, args=(log_entry, title, message), daemon=True).start()

    def _play_sound(self):
        """播放系統提示音效"""
        if WINSOUND_AVAILABLE and sys.platform.startswith("win"):
            try:
                # 播放系統 Alert 音效
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception as e:
                logger.warning(f"播放提示音失敗: {e}")

    def _show_toast(self, title: str, message: str):
        """跳出桌面 Toast 通知"""
        if PLYER_AVAILABLE:
            try:
                notification.notify(
                    title=title,
                    message=message,
                    app_name="Shioaji 觸價通知系統",
                    timeout=8
                )
            except Exception as e:
                logger.warning(f"桌面 Toast 通知跳出失敗: {e}")
        else:
            logger.info(f"[Toast] {title} - {message}")

    def _send_telegram(self, log_entry: Dict[str, Any], title: str, message: str):
        """透過 Telegram Bot API 發送訊息"""
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        text = f"🚨 *{title}*\n\n{message}\n\n⏰ 時間: `{log_entry['timestamp']}`"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, data=payload, timeout=5)
            if resp.status_code == 200:
                log_entry["telegram_sent"] = True
                logger.info(f"Telegram 通知發送成功 [{log_entry['stock_code']}]")
            else:
                logger.error(f"Telegram 通知發送失敗 (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Telegram API 連線異常: {e}")
