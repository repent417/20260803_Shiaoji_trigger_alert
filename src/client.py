"""
Shioaji Client Wrapper Module
管理 永豐金 Shioaji API 登入、股票名稱查詢、即時行情訂閱與 Mock 模擬行情產生器。
"""
import os
import time
import random
import logging
import threading
from typing import Dict, Any, Optional, Callable
from dotenv import load_dotenv

import socket

logger = logging.getLogger(__name__)

def is_internet_available(host: str = "8.8.8.8", port: int = 53, timeout: float = 2.5) -> bool:
    """速測網際網路連線狀態 (經由 DNS socket 連線測試)"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

# 嘗試載入 Shioaji 庫
try:
    import shioaji as sj
    SHIOAJI_AVAILABLE = True
except ImportError:
    SHIOAJI_AVAILABLE = False
    logger.warning("未安裝 shioaji 庫，系統將預設使用 Mock 模擬行情模式。")


class ShioajiClientWrapper:
    def __init__(self, tick_callback: Optional[Callable[[str, float, float, float], None]] = None):
        load_dotenv()
        self.api_key = os.getenv("API_KEY", "").strip("\"'")
        self.secret_key = os.getenv("SECRET_KEY", "").strip("\"'")
        self.person_id = os.getenv("PERSON_ID", "").strip("\"'")
        self.simulation = os.getenv("SIMULATION", "False").lower() in ("true", "1", "yes")

        self.api = None
        self.is_logged_in = False
        self.subscribed_codes = set()
        self.code_alias_map: Dict[str, str] = {}  # 紀錄 (TXFH6 / TXFR1 -> TXF) 等行情與規則對照
        self.tick_callback = tick_callback  # 簽名: (code, price, change, change_rate)
        self._login_lock = threading.Lock()

        self._login_lock = threading.Lock()

    def logout(self):
        """安全登出與釋放 Shioaji 連線資源"""
        if self.api:
            try:
                logger.info("正在釋放與清理前次 Shioaji API 連線資源...")
                if self.is_logged_in:
                    self.api.logout()
            except Exception as e:
                logger.warning(f"Shioaji 登出清理過程非致命例外: {e}")
        self.is_logged_in = False
        self.api = None

    def login(self) -> bool:
        """執行 Shioaji 登入 (具備併發鎖、舊連線清理與 451 異常防護)"""
        if not SHIOAJI_AVAILABLE:
            logger.info("Shioaji 套件未載入，跳過線上 API 登入。")
            return False

        if not self.api_key or self.api_key == "YOUR_API_KEY":
            logger.warning("未於 .env 設定有效的 API_KEY，將無法完成 API 登入。")
            return False

        # 防止多執行緒重複觸發登入
        if not self._login_lock.acquire(blocking=False):
            logger.warning("另一個 Shioaji 登入流程正在進行中，跳過重疊登入。")
            return False

        try:
            # 1. 先安全清理前次舊連線
            self.logout()

            logger.info(f"正在連線 永豐金 Shioaji API (simulation={self.simulation})...")
            self.api = sj.Shioaji(simulation=self.simulation)
            
            login_kwargs = {
                "api_key": self.api_key,
                "secret_key": self.secret_key
            }
            if self.person_id:
                login_kwargs["person_id"] = self.person_id

            accounts = self.api.login(**login_kwargs)

            # 檢驗回傳物件 (防範 451 Too Many Connections 字典或無效帳號)
            if isinstance(accounts, dict):
                logger.error(f"Shioaji 登入失敗 (API 回應非預期字典): {accounts}")
                self.logout()
                return False

            if not accounts:
                logger.error("Shioaji 登入失敗: 未取得可用帳號")
                self.logout()
                return False

            logger.info(f"Shioaji 登入成功！可用帳號：{accounts}")
            self.is_logged_in = True

            # 設定 Tick callback
            self._setup_callbacks()
            return True

        except Exception as e:
            logger.error(f"Shioaji 登入過程發生例外: {e}")
            self.logout()
            return False
        finally:
            self._login_lock.release()

    def _setup_callbacks(self):
        """設置 Shioaji Tick 回呼函數 (股票與期貨)"""
        if not self.api:
            return

        def on_tick_handler(exchange, tick):
            try:
                raw_code = (getattr(tick, 'code', '') or getattr(tick, 'symbol', '')).strip().upper()
                # 使用對照表找回使用者原先輸入的代號 (例如 TXFH6 -> TXF)
                code = self.code_alias_map.get(raw_code, raw_code)

                close_price = float(getattr(tick, 'close', 0.0))
                change = float(getattr(tick, 'price_chg', getattr(tick, 'change_price', 0.0)))
                change_rate = float(getattr(tick, 'pct_chg', getattr(tick, 'change_rate', 0.0)))

                if self.tick_callback and code and close_price > 0:
                    self.tick_callback(code, close_price, change, change_rate)
            except Exception as e:
                logger.error(f"Tick callback 處理異常: {e}")

        try:
            self.api.quote.set_on_tick_stk_v1_callback(on_tick_handler)
            self.api.quote.set_on_tick_fop_v1_callback(on_tick_handler)
            logger.info("已成功註冊 股票與期貨/選擇權 之即時 Tick 回呼機制")
        except Exception as e:
            logger.warning(f"設定 Tick 回呼函數失敗: {e}")

    def get_contract(self, code: str) -> Any:
        """
        智慧解析股票或期貨合約 (支援 2330, TXF, TXFR1, TX00, FITX, MXF, TMF 等簡寫與正規期貨代號)
        """
        if not self.is_logged_in or not self.api:
            return None

        c = code.strip().upper()
        # 期貨常見別名映射
        alias_map = {
            'TXF': ('TXF', 'TXFR1'), 'TX00': ('TXF', 'TXFR1'), 'FITX': ('TXF', 'TXFR1'), '台指': ('TXF', 'TXFR1'), '台指期': ('TXF', 'TXFR1'),
            'MXF': ('MXF', 'MXFR1'), 'MX00': ('MXF', 'MXFR1'), '小台': ('MXF', 'MXFR1'), '小台指': ('MXF', 'MXFR1'),
            'TMF': ('TMF', 'TMFR1'), 'TM00': ('TMF', 'TMFR1'), '微台': ('TMF', 'TMFR1'), '微台指': ('TMF', 'TMFR1')
        }

        # 1. 嘗試別名
        if c in alias_map:
            cat_name, sub_name = alias_map[c]
            try:
                cat_obj = getattr(self.api.Contracts.Futures, cat_name, None)
                if cat_obj:
                    contract = getattr(cat_obj, sub_name, None) or cat_obj[sub_name]
                    if contract:
                        return contract
            except Exception:
                pass

        # 2. 嘗試 股票合約 (Stocks)
        try:
            contract = self.api.Contracts.Stocks.get(c) or self.api.Contracts.Stocks[c]
            if contract:
                return contract
        except Exception:
            pass

        # 3. 嘗試 期貨合約 (Futures)
        try:
            # 檢查是否為期貨類別簡寫 (例如 TXF, MXF, TMF)
            if hasattr(self.api.Contracts.Futures, c):
                cat_obj = getattr(self.api.Contracts.Futures, c)
                # 預設傳回該類別之近一合約
                for preferred in ['TXFR1', 'MXFR1', 'TMFR1']:
                    if hasattr(cat_obj, preferred):
                        return getattr(cat_obj, preferred)
                # 否則傳回第一個合約
                for item in cat_obj:
                    return item

            # 檢查是否為具體期貨合約代號 (例如 TXFR1, TXF202608)
            contract = self.api.Contracts.Futures.get(c)
            if contract:
                return contract
        except Exception:
            pass

        # 4. 嘗試 選擇權合約 (Options)
        try:
            contract = self.api.Contracts.Options.get(c)
            if contract:
                return contract
        except Exception:
            pass

        return None

    def get_stock_info(self, code: str) -> Dict[str, str]:
        """
        查詢股票/期貨合約資訊 (名稱與代號)
        """
        user_code = code.strip().upper()
        default_names = {
            "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "0050": "元大台灣50",
            "TXF": "臺指期近一", "TXFR1": "臺指期近一", "TX00": "臺指期近一", "FITX": "臺指期近一",
            "MXF": "小臺指近一", "MXFR1": "小臺指近一", "MX00": "小臺指近一",
            "TMF": "微臺指近一", "TMFR1": "微臺指近一", "TM00": "微臺指近一"
        }

        name = default_names.get(user_code, f"商品 {user_code}")
        
        contract = self.get_contract(user_code)
        if contract:
            c_name = getattr(contract, 'name', '')
            if c_name:
                name = c_name

        return {"code": user_code, "name": name}

    def get_snapshot_price(self, code: str) -> Optional[Dict[str, float]]:
        """
        向 Shioaji 查詢個股/期貨之盤後快照與前一根收盤價資訊
        回傳: {"price": float, "change": float, "change_rate": float} 或 None
        """
        user_code = code.strip().upper()
        if self.is_logged_in and self.api:
            contract = self.get_contract(user_code)
            if contract:
                try:
                    snapshots = self.api.snapshots([contract])
                    if snapshots and len(snapshots) > 0:
                        snap = snapshots[0]
                        close = float(getattr(snap, 'close', 0.0))
                        ref = float(getattr(snap, 'reference_price', getattr(snap, 'open', close)))
                        change = float(getattr(snap, 'change_price', getattr(snap, 'price_chg', close - ref if ref > 0 else 0.0)))
                        change_rate = float(getattr(snap, 'pct_chg', getattr(snap, 'change_rate', (change / ref * 100.0) if ref > 0 else 0.0)))

                        if close <= 0 and ref > 0:
                            close = ref

                        if close > 0:
                            logger.info(f"已取得 [{user_code}] 快照/收盤價 = ${close:.2f} (漲跌 {change:.2f}, {change_rate:.2f}%)")
                            return {
                                "price": close,
                                "change": change,
                                "change_rate": change_rate
                            }
                except Exception as e:
                    err_msg = str(e)
                    logger.warning(f"查詢 [{user_code}] 快照失敗: {err_msg}")
                    if "401" in err_msg or "expired" in err_msg.lower():
                        logger.warning("偵測到 Shioaji Token 已過期 (401)，自動標記連線失效以觸發背景重新登入...")
                        self.is_logged_in = False

        return None

    def subscribe(self, code: str) -> bool:
        """訂閱指定股票或期貨的即時行情"""
        user_code = code.strip().upper()
        self.code_alias_map[user_code] = user_code

        if self.is_logged_in and self.api:
            contract = self.get_contract(user_code)
            if contract:
                actual_code = getattr(contract, 'code', '') or getattr(contract, 'symbol', '') or user_code
                target_code = getattr(contract, 'target_code', '')
                symbol_code = getattr(contract, 'symbol', '')

                # 建立所有可能的代號映照回原使用者代號 (例如 TXFH6 -> TXF, TXFR1 -> TXF)
                if actual_code: self.code_alias_map[actual_code.upper()] = user_code
                if target_code: self.code_alias_map[target_code.upper()] = user_code
                if symbol_code: self.code_alias_map[symbol_code.upper()] = user_code

                self.subscribed_codes.add(actual_code)
                try:
                    self.api.quote.subscribe(
                        contract,
                        quote_type=sj.constant.QuoteType.Tick,
                        version=sj.constant.QuoteVersion.v1
                    )
                    logger.info(f"已向 Shioaji 訂閱商品 [{user_code} (實際代號 {actual_code})] 即時 Tick 行情")
                    return True
                except Exception as e:
                    err_msg = str(e)
                    logger.error(f"Shioaji 訂閱 [{user_code}] 失敗: {err_msg}")
                    if "401" in err_msg or "expired" in err_msg.lower():
                        logger.warning("偵測到 Shioaji Token 已過期 (401)，自動標記連線失效以觸發背景重新登入...")
                        self.is_logged_in = False
            else:
                logger.warning(f"無法找到 [{user_code}] 之合約，仍保留訂閱名稱")
                self.subscribed_codes.add(user_code)
        else:
            self.subscribed_codes.add(user_code)

        return False

    def unsubscribe(self, code: str) -> bool:
        """取消訂閱"""
        code = code.strip().upper()
        if code in self.subscribed_codes:
            self.subscribed_codes.remove(code)

        if self.is_logged_in and self.api:
            contract = self.get_contract(code)
            if contract:
                try:
                    self.api.quote.unsubscribe(
                        contract,
                        quote_type=sj.constant.QuoteType.Tick,
                        version=sj.constant.QuoteVersion.v1
                    )
                    logger.info(f"已向 Shioaji 取消訂閱商品 [{code}]")
                    return True
                except Exception as e:
                    logger.error(f"Shioaji 取消訂閱 [{code}] 失敗: {e}")

        return False
