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
    def __init__(self, telegram_token: str = "", telegram_chat_id: str = "", telegram_enabled: bool = True):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.telegram_enabled = telegram_enabled
        self.logs: List[Dict[str, Any]] = []
        self.log_callbacks: List[Callable[[Dict[str, Any], bool], None]] = []

    def set_telegram_config(self, token: str, chat_id: str, enabled: Optional[bool] = None, save_to_env: bool = False):
        """更新 Telegram Bot 設定與開關，選擇性自動存入 .env"""
        self.telegram_token = token.strip()
        self.telegram_chat_id = chat_id.strip()
        if enabled is not None:
            self.telegram_enabled = enabled
        if save_to_env:
            self.save_telegram_config_to_env(self.telegram_token, self.telegram_chat_id, self.telegram_enabled)

    def save_telegram_config_to_env(self, token: str, chat_id: str, enabled: bool = True, env_path: str = ".env"):
        """將 Telegram 設定與啟用狀態自動寫入至環境變數 .env 檔案"""
        try:
            token = token.strip()
            chat_id = chat_id.strip()
            os.environ["TELEGRAM_BOT_TOKEN"] = token
            os.environ["TELEGRAM_CHAT_ID"] = chat_id
            os.environ["TELEGRAM_ENABLED"] = "True" if enabled else "False"

            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            has_token = False
            has_chat = False
            has_enabled = False
            new_lines = []

            for line in lines:
                if line.strip().startswith("TELEGRAM_BOT_TOKEN="):
                    new_lines.append(f"TELEGRAM_BOT_TOKEN={token}\n")
                    has_token = True
                elif line.strip().startswith("TELEGRAM_CHAT_ID="):
                    new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
                    has_chat = True
                elif line.strip().startswith("TELEGRAM_ENABLED="):
                    new_lines.append(f"TELEGRAM_ENABLED={'True' if enabled else 'False'}\n")
                    has_enabled = True
                else:
                    new_lines.append(line)

            if not has_token:
                new_lines.append(f"\nTELEGRAM_BOT_TOKEN={token}\n")
            if not has_chat:
                new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
            if not has_enabled:
                new_lines.append(f"TELEGRAM_ENABLED={'True' if enabled else 'False'}\n")

            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            logger.info(f"已自動將 Telegram Bot 設定與開關狀態寫入 {env_path}")
        except Exception as e:
            logger.error(f"寫入 .env 設定失敗: {e}")

    def add_log_callback(self, callback: Callable[[Dict[str, Any], bool], None]):
        """註冊 GUI 通知紀錄變更回呼 (接受 (log_entry, is_update))"""
        self.log_callbacks.append(callback)

    def _notify_log_callbacks(self, log_entry: Dict[str, Any], is_update: bool = False):
        """廣播通知日誌異動」"""
        for cb in self.log_callbacks:
            try:
                cb(log_entry, is_update)
            except Exception as e:
                logger.error(f"Log callback 執行失敗: {e}")

    def notify(
        self,
        title: str,
        message: str,
        stock_code: str = "",
        trigger_type: str = "",
        price: Optional[float] = None,
        bound: Optional[float] = None,
        change: float = 0.0,
        change_rate: float = 0.0,
        note: str = ""
    ):
        """
        發送多重觸價通知
        :param title: 通知標題 (例: "股價觸價警示 [2330 台積電]")
        :param message: 通知詳細內容
        :param stock_code: 股票代號
        :param trigger_type: UPPER (突破) / LOWER (跌破) / TEST (測試)
        :param price: 當前成交價
        :param bound: 觸發界線價格
        :param change: 漲跌金額
        :param change_rate: 漲跌幅 (%)
        :param note: 備註說明
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_id = f"log_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        has_config = bool(self.telegram_token and self.telegram_chat_id)
        will_send_tg = self.telegram_enabled and has_config

        if not self.telegram_enabled:
            tg_status = "DISABLED"
        elif not has_config:
            tg_status = "NOT_SET"
        else:
            tg_status = "SENDING"

        log_entry = {
            "id": log_id,
            "timestamp": timestamp,
            "title": title,
            "message": message,
            "stock_code": stock_code,
            "trigger_type": trigger_type,
            "price": price,
            "bound": bound,
            "change": change,
            "change_rate": change_rate,
            "note": note,
            "telegram_status": tg_status,
            "telegram_sent": False
        }

        # 1. 紀錄至本機 Log 列表並通知 GUI
        self.logs.append(log_entry)
        self._notify_log_callbacks(log_entry, is_update=False)

        # 2. 異步執行聲音與 Toast 彈窗 (避免阻塞主執行緒)
        threading.Thread(target=self._play_sound, daemon=True).start()
        threading.Thread(target=self._show_toast, args=(title, message), daemon=True).start()

        # 3. 異步發送 Telegram 訊息 (當開關開啟且設定存在時)
        if will_send_tg:
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
        """透過 Telegram Bot API 發送方案 A 雙欄極簡型 HTML 訊息 (精準控管行寬，絕不折行)"""
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"

        trigger_type = log_entry.get("trigger_type", "")
        timestamp = log_entry.get("timestamp", "")
        time_only = timestamp.split(" ")[-1] if " " in timestamp else timestamp
        clean_name = title.replace("股價觸價警示 ", "").replace("[", "").replace("]", "").strip()

        price = log_entry.get("price")
        bound = log_entry.get("bound")
        change_rate = log_entry.get("change_rate", 0.0)
        note = log_entry.get("note", "") or "無"

        if trigger_type == "UPPER":
            rate_str = f"▲+{change_rate:.2f}%" if change_rate >= 0 else f"▼{change_rate:.2f}%"
            p_str = f"${price:.2f}" if price is not None else "--"
            b_str = f"${bound:.2f}" if bound is not None else "--"
            html_text = (
                f"🚀🔥 <b>[{clean_name}] 突破警示</b>\n\n"
                f"• <b>成交價</b>：<code>{p_str}</code> (<code>{rate_str}</code>)\n"
                f"• <b>上界價</b>：<code>{b_str}</code>\n"
                f"• <b>備　註</b>：{note}\n"
                f"• <b>時　間</b>：<code>{time_only}</code>"
            )
        elif trigger_type == "LOWER":
            rate_str = f"▲+{change_rate:.2f}%" if change_rate >= 0 else f"▼{change_rate:.2f}%"
            p_str = f"${price:.2f}" if price is not None else "--"
            b_str = f"${bound:.2f}" if bound is not None else "--"
            html_text = (
                f"❄️📉 <b>[{clean_name}] 跌破警示</b>\n\n"
                f"• <b>成交價</b>：<code>{p_str}</code> (<code>{rate_str}</code>)\n"
                f"• <b>下界價</b>：<code>{b_str}</code>\n"
                f"• <b>備　註</b>：{note}\n"
                f"• <b>時　間</b>：<code>{time_only}</code>"
            )
        elif trigger_type == "TEST":
            html_text = (
                f"🔔📱 <b>【Telegram 測試連線成功】</b>\n\n"
                f"• <b>狀　態</b>：<code>已連線成功</code>\n"
                f"• <b>系統名</b>：<code>Shioaji 觸價通知</code>\n"
                f"• <b>時　間</b>：<code>{time_only}</code>"
            )
        else:
            html_text = (
                f"📢⚡ <b>[{clean_name}] 觸價通知</b>\n\n"
                f"• <b>內　容</b>：{message}\n"
                f"• <b>時　間</b>：<code>{time_only}</code>"
            )

        payload = {
            "chat_id": self.telegram_chat_id,
            "text": html_text,
            "parse_mode": "HTML"
        }
        try:
            resp = requests.post(url, data=payload, timeout=5)
            if resp.status_code == 200:
                log_entry["telegram_status"] = "SENT"
                log_entry["telegram_sent"] = True
                logger.info(f"Telegram 通知發送成功 [{log_entry.get('stock_code', '')}]")
            else:
                log_entry["telegram_status"] = "FAILED"
                log_entry["telegram_sent"] = False
                logger.error(f"Telegram 通知發送失敗 (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            log_entry["telegram_status"] = "FAILED"
            log_entry["telegram_sent"] = False
            logger.error(f"Telegram API 連線異常: {e}")

        # 廣播異步狀態更新至 GUI
        self._notify_log_callbacks(log_entry, is_update=True)
