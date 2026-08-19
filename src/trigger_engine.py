"""
Trigger Engine Module
提供觸價條件設定數據模型、即時價格比對、狀態切換與事件觸發機制。
"""
import logging
from datetime import datetime, time
from typing import Dict, Any, List, Optional, Callable
from src.storage import StorageManager
from src.notifier import Notifier

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "Active"       # 監控中
STATUS_TRIGGERED = "Triggered" # 已觸發
STATUS_PAUSED = "Paused"       # 已暫停

def is_futures_or_index(code: str) -> bool:
    """判斷商品代號是否為期貨或指數 (如 TXF, MXF, TMF 等非純數字代碼)"""
    c = code.strip().upper()
    return not c.isdigit()

def is_in_trading_hours(code: str, now_dt: Optional[datetime] = None, bypass_for_testing: bool = False) -> bool:
    """
    檢查當前時間是否屬於該商品的【正式開盤交易時間】
    精準過濾 08:30-08:59 現股與 08:30-08:44 期貨之試撮盤
    """
    if bypass_for_testing:
        return True
    if now_dt is None:
        now_dt = datetime.now()

    weekday = now_dt.weekday()  # 0=Mon, 1=Tue, ..., 4=Fri, 5=Sat, 6=Sun
    now_time = now_dt.time()

    if is_futures_or_index(code):
        # 【台指期 / 指數期貨】交易時間：
        # 日盤：08:45:00 ~ 13:45:00 (過濾 08:30 ~ 08:44:59 試撮)
        # 夜盤：15:00:00 ~ 翌日 05:00:00 (跨日)
        if weekday < 5 and time(8, 45, 0) <= now_time <= time(13, 45, 0):
            return True
        if (weekday < 5 and now_time >= time(15, 0, 0)) or (0 < weekday < 6 and now_time <= time(5, 0, 0)):
            return True
        return False
    else:
        # 【現股 / 股票 / ETF】交易時間：
        # 正式盤：09:00:00 ~ 13:25:00 (過濾 08:30~08:59 盤前試撮與 13:25~13:30 收盤試撮)
        if weekday < 5 and time(9, 0, 0) <= now_time < time(13, 25, 0):
            return True
        return False

class TriggerRule:
    def __init__(
        self,
        code: str,
        name: str = "",
        upper_bound: Optional[float] = None,
        lower_bound: Optional[float] = None,
        status: str = STATUS_ACTIVE,
        last_price: float = 0.0,
        change: float = 0.0,
        change_rate: float = 0.0,
        triggered_type: Optional[str] = None,
        triggered_price: Optional[float] = None,
        triggered_at: Optional[str] = None,
        note: str = "",
        order_index: int = 0,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None
    ):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.code = code.strip()
        self.name = name.strip() or code
        self.upper_bound = float(upper_bound) if upper_bound is not None and upper_bound != "" else None
        self.lower_bound = float(lower_bound) if lower_bound is not None and lower_bound != "" else None
        self.status = status
        self.last_price = float(last_price)
        self.change = float(change)
        self.change_rate = float(change_rate)
        self.triggered_type = triggered_type  # "UPPER" 或 "LOWER"
        self.triggered_price = float(triggered_price) if triggered_price is not None else None
        self.triggered_at = triggered_at
        self.note = note
        self.order_index = int(order_index)
        self.created_at = created_at or now_str
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> Dict[str, Any]:
        """序列化為字典用於儲存"""
        return {
            "code": self.code,
            "name": self.name,
            "upper_bound": self.upper_bound,
            "lower_bound": self.lower_bound,
            "status": self.status,
            "last_price": self.last_price,
            "change": self.change,
            "change_rate": self.change_rate,
            "triggered_type": self.triggered_type,
            "triggered_price": self.triggered_price,
            "triggered_at": self.triggered_at,
            "note": self.note,
            "order_index": self.order_index,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TriggerRule':
        """自字典反序列化建構物件"""
        return cls(
            code=data.get("code", ""),
            name=data.get("name", ""),
            upper_bound=data.get("upper_bound"),
            lower_bound=data.get("lower_bound"),
            status=data.get("status", STATUS_ACTIVE),
            last_price=data.get("last_price", 0.0),
            change=data.get("change", 0.0),
            change_rate=data.get("change_rate", 0.0),
            triggered_type=data.get("triggered_type"),
            triggered_price=data.get("triggered_price"),
            triggered_at=data.get("triggered_at"),
            note=data.get("note", ""),
            order_index=data.get("order_index", 0),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at")
        )


class TriggerEngine:
    def __init__(self, notifier: Notifier, storage: Optional[StorageManager] = None):
        self.notifier = notifier
        self.storage = storage or StorageManager()
        self.rules: Dict[str, TriggerRule] = {}
        self.update_callbacks: List[Callable[[TriggerRule], None]] = []
        self.load_from_storage()

    def add_update_callback(self, callback: Callable[[TriggerRule, bool], None]):
        """註冊規則異動或價格更新回呼 (簽名: (rule, is_deleted))"""
        self.update_callbacks.append(callback)

    def _notify_callbacks(self, rule: TriggerRule, is_deleted: bool = False):
        """廣播更新至所有監聽者"""
        for cb in self.update_callbacks:
            try:
                # 嘗試帶 is_deleted 呼叫，相容舊簽名
                try:
                    cb(rule, is_deleted)
                except TypeError:
                    cb(rule)
            except Exception as e:
                logger.error(f"Engine update callback 異常: {e}")

    def load_from_storage(self):
        """從本地 JSON 載入觸價規則，並依 order_index 排序"""
        raw_list = self.storage.load_rules()
        self.rules.clear()
        # 依 order_index 排序
        raw_list.sort(key=lambda x: x.get("order_index", 0))
        for idx, item in enumerate(raw_list):
            item["order_index"] = idx
            rule = TriggerRule.from_dict(item)
            if rule.code:
                self.rules[rule.code] = rule
        logger.info(f"TriggerEngine 已載入 {len(self.rules)} 條規則")

    def save_to_storage(self):
        """儲存現有觸價規則至本地 JSON」"""
        ordered_rules = sorted(self.rules.values(), key=lambda r: r.order_index)
        raw_list = [rule.to_dict() for rule in ordered_rules]
        self.storage.save_rules(raw_list)

    def add_or_update_rule(
        self,
        code: str,
        name: str = "",
        upper_bound: Optional[float] = None,
        lower_bound: Optional[float] = None,
        note: str = ""
    ) -> TriggerRule:
        """新增或更新觸價條件"""
        code = code.strip().upper()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if code in self.rules:
            rule = self.rules[code]
            if name:
                rule.name = name
            rule.upper_bound = upper_bound
            rule.lower_bound = lower_bound
            rule.note = note
            rule.updated_at = now_str
            # 如果修改規則，自動重置為 Active
            rule.status = STATUS_ACTIVE
            rule.triggered_type = None
            rule.triggered_price = None
            rule.triggered_at = None
        else:
            rule = TriggerRule(
                code=code,
                name=name or code,
                upper_bound=upper_bound,
                lower_bound=lower_bound,
                status=STATUS_ACTIVE,
                note=note,
                order_index=len(self.rules),
                created_at=now_str,
                updated_at=now_str
            )
            self.rules[code] = rule

        self.save_to_storage()
        self._notify_callbacks(rule, is_deleted=False)
        return rule

    def reorder_by_codes(self, ordered_codes: List[str]):
        """依傳入的股票代號順序重排所有規則」"""
        new_dict = {}
        for idx, code in enumerate(ordered_codes):
            code = code.strip().upper()
            if code in self.rules:
                rule = self.rules[code]
                rule.order_index = idx
                new_dict[code] = rule

        # 補上未在傳入清單中的規則
        for code, rule in self.rules.items():
            if code not in new_dict:
                rule.order_index = len(new_dict)
                new_dict[code] = rule

        self.rules = new_dict
        self.save_to_storage()

    def move_rule(self, code: str, direction: str) -> bool:
        """
        手動調整單一項目順序
        :param direction: 'UP' | 'DOWN' | 'TOP' | 'BOTTOM'
        """
        code = code.strip().upper()
        if code not in self.rules:
            return False

        ordered_codes = [r.code for r in sorted(self.rules.values(), key=lambda r: r.order_index)]
        idx = ordered_codes.index(code)

        if direction == "UP" and idx > 0:
            ordered_codes[idx], ordered_codes[idx - 1] = ordered_codes[idx - 1], ordered_codes[idx]
        elif direction == "DOWN" and idx < len(ordered_codes) - 1:
            ordered_codes[idx], ordered_codes[idx + 1] = ordered_codes[idx + 1], ordered_codes[idx]
        elif direction == "TOP" and idx > 0:
            item = ordered_codes.pop(idx)
            ordered_codes.insert(0, item)
        elif direction == "BOTTOM" and idx < len(ordered_codes) - 1:
            item = ordered_codes.pop(idx)
            ordered_codes.append(item)
        else:
            return False

        self.reorder_by_codes(ordered_codes)
        return True

    def remove_rule(self, code: str) -> bool:
        """刪除指定股票觸價單"""
        code = code.strip().upper()
        if code in self.rules:
            rule = self.rules.pop(code)
            self.save_to_storage()
            self._notify_callbacks(rule, is_deleted=True)
            return True
        return False

    def toggle_pause(self, code: str):
        """切換 監控中 / 已暫停 狀態"""
        code = code.strip().upper()
        if code in self.rules:
            rule = self.rules[code]
            if rule.status == STATUS_PAUSED:
                rule.status = STATUS_ACTIVE
            elif rule.status == STATUS_ACTIVE:
                rule.status = STATUS_PAUSED
            self.save_to_storage()
            self._notify_callbacks(rule)

    def reset_trigger(self, code: str):
        """重置已觸發之規則回到 ACTIVE 狀態"""
        code = code.strip().upper()
        if code in self.rules:
            rule = self.rules[code]
            rule.status = STATUS_ACTIVE
            rule.triggered_type = None
            rule.triggered_price = None
            rule.triggered_at = None
            self.save_to_storage()
            self._notify_callbacks(rule)

    def process_tick(self, code: str, price: float, change: float = 0.0, change_rate: float = 0.0, bypass_time_check: bool = False):
        """
        即時比對 Tick 價格
        :param code: 股票代號
        :param price: 當前成交價
        :param change: 漲跌金額
        :param change_rate: 漲跌幅 (%)
        :param bypass_time_check: 是否過濾交易時間限制 (如測試模式或 Mock 時傳入 True)
        """
        code = code.strip().upper()
        target_code = code
        if target_code not in self.rules:
            # 別名容錯尋找 (例如傳入 TXFH6 或 TXFR1，但規則為 TXF)
            for r_code in self.rules.keys():
                if (r_code in target_code) or (target_code in r_code) or (r_code in ['TXF', 'TX00', 'FITX'] and 'TXF' in target_code):
                    target_code = r_code
                    break

        if target_code not in self.rules:
            return

        rule = self.rules[target_code]
        rule.last_price = float(price)
        rule.change = float(change)
        rule.change_rate = float(change_rate)

        # 僅在 ACTIVE 狀態 且 處於【正式開盤交易時間】才進行觸價判斷
        if rule.status == STATUS_ACTIVE:
            # 時間檢測 (過濾 08:30~08:59:59 試撮盤)
            if not is_in_trading_hours(rule.code, bypass_for_testing=bypass_time_check):
                self._notify_callbacks(rule)
                return

            triggered = False
            t_type = None
            t_msg = ""

            # 檢查突破上界
            if rule.upper_bound is not None and price >= rule.upper_bound:
                triggered = True
                t_type = "UPPER"
                t_msg = f"成交價 ${price:.2f} 已【突破上界】 ${rule.upper_bound:.2f}！"

            # 檢查跌破下界
            elif rule.lower_bound is not None and price <= rule.lower_bound:
                triggered = True
                t_type = "LOWER"
                t_msg = f"成交價 ${price:.2f} 已【跌破下界】 ${rule.lower_bound:.2f}！"

            if triggered:
                rule.status = STATUS_TRIGGERED
                rule.triggered_type = t_type
                rule.triggered_price = price
                rule.triggered_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                bound_val = rule.upper_bound if t_type == "UPPER" else rule.lower_bound
                title = f"[{rule.code} {rule.name}]"
                full_msg = f"成交價 ${price:.2f} 已【{'突破上界' if t_type == 'UPPER' else '跌破下界'}】 ${bound_val:.2f}！"

                # 發送多重通知
                self.notifier.notify(
                    title=title,
                    message=full_msg,
                    stock_code=rule.code,
                    trigger_type=t_type,
                    price=price,
                    bound=bound_val,
                    change=change,
                    change_rate=change_rate,
                    note=rule.note or "無"
                )
                self.save_to_storage()

        self._notify_callbacks(rule)
