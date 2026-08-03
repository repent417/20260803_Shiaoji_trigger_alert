"""
Trigger Engine Module
提供觸價條件設定數據模型、即時價格比對、狀態切換與事件觸發機制。
"""
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from src.storage import StorageManager
from src.notifier import Notifier

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "Active"       # 監控中
STATUS_TRIGGERED = "Triggered" # 已觸發
STATUS_PAUSED = "Paused"       # 已暫停

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
        note: str = ""
    ):
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
            "note": self.note
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
            note=data.get("note", "")
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
        """從本地 JSON 載入觸價規則"""
        raw_list = self.storage.load_rules()
        self.rules.clear()
        for item in raw_list:
            rule = TriggerRule.from_dict(item)
            if rule.code:
                self.rules[rule.code] = rule
        logger.info(f"TriggerEngine 已載入 {len(self.rules)} 條規則")

    def save_to_storage(self):
        """儲存現有觸價規則至本地 JSON"""
        raw_list = [rule.to_dict() for rule in self.rules.values()]
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
        if code in self.rules:
            rule = self.rules[code]
            if name:
                rule.name = name
            rule.upper_bound = upper_bound
            rule.lower_bound = lower_bound
            rule.note = note
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
                note=note
            )
            self.rules[code] = rule

        self.save_to_storage()
        self._notify_callbacks(rule, is_deleted=False)
        return rule

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

    def process_tick(self, code: str, price: float, change: float = 0.0, change_rate: float = 0.0):
        """
        即時比對 Tick 價格
        :param code: 股票代號
        :param price: 當前成交價
        :param change: 漲跌金額
        :param change_rate: 漲跌幅 (%)
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

        # 僅在 ACTIVE 狀態進行觸價判斷
        if rule.status == STATUS_ACTIVE:
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

                title = f"股價觸價警示 [{rule.code} {rule.name}]"
                full_msg = f"{t_msg}\n即時價格: ${price:.2f} (漲跌: {change:+.2f}, {change_rate:+.2f}%)\n備註: {rule.note or '無'}"
                
                # 發送多重通知
                self.notifier.notify(
                    title=title,
                    message=full_msg,
                    stock_code=rule.code,
                    trigger_type=t_type
                )
                self.save_to_storage()

        self._notify_callbacks(rule)
