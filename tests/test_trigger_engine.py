"""
Unit tests for TriggerEngine and StorageManager
"""
import os
import unittest
import tempfile
from src.notifier import Notifier
from src.storage import StorageManager
from src.trigger_engine import TriggerEngine, STATUS_ACTIVE, STATUS_TRIGGERED, STATUS_PAUSED

class TestTriggerEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file = os.path.join(self.temp_dir.name, "test_rules.json")
        self.storage = StorageManager(filepath=self.temp_file)
        self.notifier = Notifier()
        self.engine = TriggerEngine(notifier=self.notifier, storage=self.storage)

    def test_sanitize_filename(self):
        from src.storage import sanitize_filename
        long_name = "a" * 100 + ".json"
        sanitized = sanitize_filename(long_name, 70)
        self.assertLessEqual(len(os.path.basename(sanitized)), 70)
        self.assertTrue(sanitized.endswith(".json"))

    def test_add_rule(self):
        rule = self.engine.add_or_update_rule(
            code="2330",
            name="台積電",
            upper_bound=880.0,
            lower_bound=820.0,
            note="測試上界下界"
        )
        self.assertEqual(rule.code, "2330")
        self.assertEqual(rule.name, "台積電")
        self.assertEqual(rule.upper_bound, 880.0)
        self.assertEqual(rule.lower_bound, 820.0)
        self.assertEqual(rule.status, STATUS_ACTIVE)
        self.assertIsNotNone(rule.created_at)
        self.assertIsNotNone(rule.updated_at)

    def test_upper_trigger(self):
        self.engine.add_or_update_rule(
            code="2330",
            name="台積電",
            upper_bound=880.0,
            lower_bound=820.0
        )
        # 價格小於 880，未觸發
        self.engine.process_tick("2330", 870.0, change=10.0, change_rate=1.16, bypass_time_check=True)
        rule = self.engine.rules["2330"]
        self.assertEqual(rule.status, STATUS_ACTIVE)

        # 價格達到 885，觸發突破上界
        self.engine.process_tick("2330", 885.0, change=25.0, change_rate=2.9, bypass_time_check=True)
        self.assertEqual(rule.status, STATUS_TRIGGERED)
        self.assertEqual(rule.triggered_type, "UPPER")
        self.assertEqual(rule.triggered_price, 885.0)

    def test_lower_trigger(self):
        self.engine.add_or_update_rule(
            code="2317",
            name="鴻海",
            upper_bound=220.0,
            lower_bound=190.0
        )
        # 價格高於 190，未觸發
        self.engine.process_tick("2317", 195.0, change=-2.0, change_rate=-1.0, bypass_time_check=True)
        rule = self.engine.rules["2317"]
        self.assertEqual(rule.status, STATUS_ACTIVE)

        # 價格跌至 188，觸發跌破下界
        self.engine.process_tick("2317", 188.0, change=-9.0, change_rate=-4.5, bypass_time_check=True)
        self.assertEqual(rule.status, STATUS_TRIGGERED)
        self.assertEqual(rule.triggered_type, "LOWER")
        self.assertEqual(rule.triggered_price, 188.0)

    def test_reset_and_pause(self):
        rule = self.engine.add_or_update_rule(code="0050", upper_bound=160.0)
        self.engine.process_tick("0050", 165.0, bypass_time_check=True)
        self.assertEqual(rule.status, STATUS_TRIGGERED)

        # 重置
        self.engine.reset_trigger("0050")
        self.assertEqual(rule.status, STATUS_ACTIVE)
        self.assertIsNone(rule.triggered_type)

        # 暫停
        self.engine.toggle_pause("0050")
        self.assertEqual(rule.status, STATUS_PAUSED)

        # 暫停期間價格再超過上界，不應觸發
        self.engine.process_tick("0050", 170.0, bypass_time_check=True)
        self.assertEqual(rule.status, STATUS_PAUSED)

    def test_trading_hours_filter(self):
        from datetime import datetime
        from src.trigger_engine import is_in_trading_hours
        # 測試 08:40 現股試撮盤 (應回傳 False)
        dt_trial = datetime(2026, 8, 4, 8, 40, 0)
        self.assertFalse(is_in_trading_hours("2330", dt_trial))

        # 測試 09:05 現股盤中正式交易時間 (應回傳 True)
        dt_open = datetime(2026, 8, 4, 9, 5, 0)
        self.assertTrue(is_in_trading_hours("2330", dt_open))

        # 測試 13:26 現股收盤試撮時間 (應回傳 False，過濾 13:25~13:30 試撮假價格)
        dt_close_trial = datetime(2026, 8, 4, 13, 26, 0)
        self.assertFalse(is_in_trading_hours("2330", dt_close_trial))

        # 測試 08:40 期貨試撮盤 (應回傳 False)
        self.assertFalse(is_in_trading_hours("TXF", dt_trial))

        # 測試 08:50 期貨盤中正式交易時間 (應回傳 True)
        dt_fut_open = datetime(2026, 8, 4, 8, 50, 0)
        self.assertTrue(is_in_trading_hours("TXF", dt_fut_open))

    def test_remove_rule_notification(self):
        deleted_events = []
        def on_update(rule, is_deleted=False):
            if is_deleted:
                deleted_events.append(rule.code)

        self.engine.add_update_callback(on_update)
        self.engine.add_or_update_rule(code="TXF", name="臺指期", upper_bound=24000.0)
        self.assertIn("TXF", self.engine.rules)

        # 刪除
        removed = self.engine.remove_rule("TXF")
        self.assertTrue(removed)
        self.assertNotIn("TXF", self.engine.rules)
        self.assertIn("TXF", deleted_events)

    def test_get_snapshot_price(self):
        from src.client import ShioajiClientWrapper
        client = ShioajiClientWrapper()
        snapshot = client.get_snapshot_price("2330")
        self.assertIsNotNone(snapshot)
        self.assertIn("price", snapshot)
        self.assertGreater(snapshot["price"], 0.0)

if __name__ == "__main__":
    unittest.main()
