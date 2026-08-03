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

logger = logging.getLogger(__name__)

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
        self.simulation = os.getenv("SIMULATION", "True").lower() in ("true", "1", "yes")

        self.api = None
        self.is_logged_in = False
        self.subscribed_codes = set()
        self.tick_callback = tick_callback  # 簽名: (code, price, change, change_rate)

        # Mock 模擬發送器
        self.mock_running = False
        self.mock_thread = None
        self.mock_prices: Dict[str, float] = {
            "2330": 850.0,
            "2317": 200.0,
            "2454": 1200.0,
            "0050": 160.0
        }

    def login(self) -> bool:
        """執行 Shioaji 登入"""
        if not SHIOAJI_AVAILABLE:
            logger.info("Shioaji 套件未載入，跳過線上 API 登入。")
            return False

        if not self.api_key or self.api_key == "YOUR_API_KEY":
            logger.warning("未於 .env 設定有效的 API_KEY，將無法完成 API 登入。")
            return False

        try:
            logger.info(f"正在連線 永豐金 Shioaji API (simulation={self.simulation})...")
            self.api = sj.Shioaji(simulation=self.simulation)
            
            login_kwargs = {
                "api_key": self.api_key,
                "secret_key": self.secret_key
            }
            if self.person_id:
                login_kwargs["person_id"] = self.person_id

            accounts = self.api.login(**login_kwargs)
            logger.info(f"Shioaji 登入成功！可用帳號：{accounts}")
            self.is_logged_in = True

            # 設定 Tick callback
            self._setup_callbacks()
            return True

        except Exception as e:
            logger.error(f"Shioaji 登入過程發生例外: {e}")
            self.is_logged_in = False
            return False

    def _setup_callbacks(self):
        """設置 Shioaji Tick 回呼函數"""
        if not self.api:
            return

        def on_tick_stk(exchange, tick):
            try:
                code = getattr(tick, 'code', '')
                close_price = float(getattr(tick, 'close', 0.0))
                # 漲跌幅度
                change = float(getattr(tick, 'change_price', 0.0))
                change_rate = float(getattr(tick, 'change_rate', 0.0))
                if self.tick_callback and code and close_price > 0:
                    self.tick_callback(code, close_price, change, change_rate)
            except Exception as e:
                logger.error(f"Tick stk callback 處理異常: {e}")

        try:
            self.api.quote.set_on_tick_stk_v1_callback(on_tick_stk)
        except Exception as e:
            logger.warning(f"設定 set_on_tick_stk_v1_callback 失敗: {e}")

    def get_stock_info(self, code: str) -> Dict[str, str]:
        """
        查詢股票合約資訊 (名稱與市場類別)
        """
        code = code.strip().upper()
        default_names = {
            "2330": "台積電",
            "2317": "鴻海",
            "2454": "聯發科",
            "0050": "元大台灣50",
            "2308": "台達電",
            "2382": "廣達",
            "3231": "緯創",
            "2603": "長榮"
        }

        name = default_names.get(code, f"個股 {code}")
        
        if self.is_logged_in and self.api:
            try:
                contract = self.api.Contracts.Stocks.get(code) or self.api.Contracts.Stocks[code]
                if contract:
                    name = getattr(contract, 'name', name) or name
            except Exception as e:
                logger.debug(f"合約查詢 {code} 失敗或無結果: {e}")

        return {"code": code, "name": name}

    def subscribe(self, code: str) -> bool:
        """訂閱指定股票的即時行情"""
        code = code.strip().upper()
        self.subscribed_codes.add(code)

        if self.is_logged_in and self.api:
            try:
                contract = self.api.Contracts.Stocks.get(code) or self.api.Contracts.Stocks[code]
                if contract:
                    self.api.quote.subscribe(
                        contract,
                        quote_type=sj.constant.QuoteType.Tick,
                        version=sj.constant.QuoteVersion.v1
                    )
                    logger.info(f"已向 Shioaji 訂閱 {code} 即時 Tick 行情")
                    return True
            except Exception as e:
                logger.error(f"Shioaji 訂閱 {code} 失敗: {e}")

        # 若離線，設定初始 mock 價格
        if code not in self.mock_prices:
            self.mock_prices[code] = 100.0

        return False

    def unsubscribe(self, code: str) -> bool:
        """取消訂閱"""
        code = code.strip().upper()
        if code in self.subscribed_codes:
            self.subscribed_codes.remove(code)

        if self.is_logged_in and self.api:
            try:
                contract = self.api.Contracts.Stocks.get(code) or self.api.Contracts.Stocks[code]
                if contract:
                    self.api.quote.unsubscribe(
                        contract,
                        quote_type=sj.constant.QuoteType.Tick,
                        version=sj.constant.QuoteVersion.v1
                    )
                    logger.info(f"已向 Shioaji 取消訂閱 {code}")
                    return True
            except Exception as e:
                logger.error(f"Shioaji 取消訂閱 {code} 失敗: {e}")

        return False

    # --- 模擬 Tick 觸發器 (用於無 API Key 或盤後測試 GUI) ---

    def start_mock_ticks(self, target_codes: Optional[list] = None):
        """啟動模擬行情發送器"""
        if self.mock_running:
            return

        self.mock_running = True
        self.mock_thread = threading.Thread(target=self._mock_loop, daemon=True)
        self.mock_thread.start()
        logger.info("已啟動 Mock 模擬行情發送器")

    def stop_mock_ticks(self):
        """停止模擬行情發送器"""
        self.mock_running = False
        logger.info("已停止 Mock 模擬行情發送器")

    def _mock_loop(self):
        """模擬價格波動與發送循環"""
        while self.mock_running:
            codes_to_run = list(self.subscribed_codes) or list(self.mock_prices.keys())
            for code in codes_to_run:
                if not self.mock_running:
                    break
                curr_price = self.mock_prices.get(code, 100.0)
                # 隨機價格波動 ±0.5% ~ ±1.5%
                delta_pct = random.uniform(-0.012, 0.012)
                new_price = round(curr_price * (1 + delta_pct), 2)
                if new_price <= 0.1:
                    new_price = 1.0
                
                self.mock_prices[code] = new_price
                change = round(new_price - curr_price, 2)
                change_rate = round((change / curr_price) * 100, 2)

                if self.tick_callback:
                    self.tick_callback(code, new_price, change, change_rate)

                time.sleep(1.0)
            time.sleep(1.0)

    def trigger_manual_mock_tick(self, code: str, price: float):
        """手動注入指定價格的 Mock Tick (利於測試突破/跌破)"""
        code = code.strip().upper()
        self.mock_prices[code] = price
        if self.tick_callback:
            self.tick_callback(code, price, 0.0, 0.0)
        logger.info(f"手動注入 Mock Tick [{code}] 價格 = ${price}")
