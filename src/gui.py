"""
Graphical User Interface (GUI) Module
基於 Tkinter + TTK 的現代化即時股價觸價通知系統 GUI。
"""
import os
import queue
import logging
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
from typing import Optional, Dict, Any

import threading
import time

from src.storage import StorageManager
from src.notifier import Notifier
from src.trigger_engine import TriggerEngine, TriggerRule, STATUS_ACTIVE, STATUS_TRIGGERED, STATUS_PAUSED
from src.client import ShioajiClientWrapper, is_internet_available

logger = logging.getLogger(__name__)

class MainGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("永豐金 Shioaji 即時股價觸價通知系統 v1.0")
        self.geometry("1300x840")
        self.minsize(1000, 680)

        # 核心模組初始化
        self.notifier = Notifier()
        self.storage = StorageManager()
        self.engine = TriggerEngine(notifier=self.notifier, storage=self.storage)
        self.client = ShioajiClientWrapper(tick_callback=self._on_tick_received)

        # Telegram 初步設定載入
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
        tg_enabled_env = os.getenv("TELEGRAM_ENABLED", "True").strip().lower() != "false"
        self.notifier.set_telegram_config(tg_token, tg_chat, enabled=tg_enabled_env)

        # 佇列機制 (確保 Thread-Safe 更新 UI)
        self.gui_queue = queue.Queue()

        # 互動狀態與網路監控
        self._selection_timer = None
        self._hover_item = None
        self._is_closing = False
        self.is_network_connected = is_internet_available()
        self.network_warned = False
        self._drag_item = None
        self.sort_state = None  # None (手動自訂) | ("code", "ASC") | ("code", "DESC") | ("status", "ASC") | ("status", "DESC")
        self._cell_labels: Dict[str, tk.Label] = {}  # 專屬於「漲跌幅」單欄的文字標籤字典

        # 註冊 Engine 與 Notifier 的異動廣播
        self.engine.add_update_callback(self._on_rule_updated)
        self.notifier.add_log_callback(self._on_notification_log_added)

        # 建構 UI
        self._setup_styles()
        self._build_header_bar()
        self._build_form_frame()
        self._build_table_frame()
        self._build_log_frame()
        self._build_status_bar()

        # 右鍵選單初始化
        self._create_context_menu()

        # 視窗關閉處理
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 定時輪詢 GUI 佇列與背景網路連線監控
        self.after(100, self._process_gui_queue)
        self._start_network_monitor()

        # 初始化資料展示
        self._reload_all_rules_in_ui()
        self._update_connection_status_ui()

        # 試圖自動進行 Shioaji 登入，若無 API Key 則啟動模擬測試模式
        self._auto_start()

    def _setup_styles(self):
        """設定跨平台 TTK 視覺主題風格"""
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # 顏色設定
        PRIMARY_COLOR = "#2A3F54"
        BG_COLOR = "#F7F9FA"

        self.configure(bg=BG_COLOR)
        
        self.style.configure(".", font=("Microsoft JhengHei", 10), background=BG_COLOR)
        self.style.configure("Header.TFrame", background=PRIMARY_COLOR)
        self.style.configure("Header.TLabel", background=PRIMARY_COLOR, foreground="#FFFFFF", font=("Microsoft JhengHei", 12, "bold"))
        self.style.configure("Card.TFrame", background="#FFFFFF", relief="solid", borderwidth=1)
        self.style.configure("Primary.TButton", font=("Microsoft JhengHei", 10, "bold"), padding=6)
        self.style.configure("Warning.TButton", font=("Microsoft JhengHei", 10, "bold"), padding=6)
        self.style.configure("Accent.TButton", font=("Microsoft JhengHei", 10, "bold"), padding=6)
        
        # Treeview 表格樣式
        self.style.configure("Treeview", font=("Microsoft JhengHei", 10), rowheight=28)
        self.style.configure("Treeview.Heading", font=("Microsoft JhengHei", 10, "bold"), padding=5)

    def _build_header_bar(self):
        """頂部狀態與控制欄"""
        header_frame = ttk.Frame(self, style="Header.TFrame", padding=10)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        # 標題
        lbl_title = ttk.Label(header_frame, text="📈 永豐金 Shioaji 即時股價觸價通知系統", style="Header.TLabel")
        lbl_title.pack(side=tk.LEFT, padx=10)

        # 右側控制區
        right_panel = ttk.Frame(header_frame, style="Header.TFrame")
        right_panel.pack(side=tk.RIGHT, padx=10)

        # 狀態燈
        self.lbl_api_status = tk.Label(right_panel, text="⚪ Shioaji: 離線", bg="#555555", fg="#FFFFFF", font=("Microsoft JhengHei", 9, "bold"), padx=8, pady=3)
        self.lbl_api_status.pack(side=tk.LEFT, padx=5)

        self.lbl_tg_status = tk.Label(right_panel, text="⚪ Telegram: 未設定", bg="#555555", fg="#FFFFFF", font=("Microsoft JhengHei", 9, "bold"), padx=8, pady=3)
        self.lbl_tg_status.pack(side=tk.LEFT, padx=5)

        # Telegram 推播可選開關
        self.var_tg_enable = tk.BooleanVar(value=self.notifier.telegram_enabled)
        self.chk_tg = tk.Checkbutton(
            right_panel,
            text="📱 啟用 Telegram",
            variable=self.var_tg_enable,
            command=self._on_toggle_tg_enable,
            bg="#2A3F54",
            fg="#FFFFFF",
            selectcolor="#2A3F54",
            activebackground="#2A3F54",
            activeforeground="#FFFFFF",
            font=("Microsoft JhengHei", 9, "bold")
        )
        self.chk_tg.pack(side=tk.LEFT, padx=5)

        # 控制按鈕
        self.btn_login = ttk.Button(right_panel, text="🔑 登入 API", command=self._on_click_login, style="Primary.TButton")
        self.btn_login.pack(side=tk.LEFT, padx=4)

        self.btn_mock = ttk.Button(right_panel, text="🧪 啟動模擬行情", command=self._on_toggle_mock)
        self.btn_mock.pack(side=tk.LEFT, padx=4)

        btn_tg_config = ttk.Button(right_panel, text="⚙️ Telegram 設定", command=self._on_click_tg_config)
        btn_tg_config.pack(side=tk.LEFT, padx=4)

    def _build_form_frame(self):
        """觸價規則新增與編輯表單」區塊"""
        card = ttk.LabelFrame(self, text=" ➕ 新增 / 編輯股價觸價條件 ", padding=12)
        card.pack(side=tk.TOP, fill=tk.X, padx=12, pady=8)

        form_grid = ttk.Frame(card)
        form_grid.pack(fill=tk.X)

        # 股票代號
        ttk.Label(form_grid, text="股票代號:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.ent_code = ttk.Entry(form_grid, width=12, font=("Microsoft JhengHei", 10, "bold"))
        self.ent_code.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        self.ent_code.bind("<FocusOut>", self._on_code_focus_out)
        self.ent_code.bind("<Return>", self._on_code_focus_out)

        # 股票名稱
        ttk.Label(form_grid, text="股票名稱:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        self.ent_name = ttk.Entry(form_grid, width=16)
        self.ent_name.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)

        # 價格上界 (突破)
        ttk.Label(form_grid, text="價格上界 (突破通知):").grid(row=0, column=4, sticky=tk.W, padx=5, pady=5)
        self.ent_upper = ttk.Entry(form_grid, width=12, font=("Microsoft JhengHei", 10, "bold"), foreground="#CC0000")
        self.ent_upper.grid(row=0, column=5, sticky=tk.W, padx=5, pady=5)

        # 價格下界 (跌破)
        ttk.Label(form_grid, text="價格下界 (跌破通知):").grid(row=0, column=6, sticky=tk.W, padx=5, pady=5)
        self.ent_lower = ttk.Entry(form_grid, width=12, font=("Microsoft JhengHei", 10, "bold"), foreground="#008000")
        self.ent_lower.grid(row=0, column=7, sticky=tk.W, padx=5, pady=5)

        # 備註
        ttk.Label(form_grid, text="備註說明:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.ent_note = ttk.Entry(form_grid, width=40)
        self.ent_note.grid(row=1, column=1, columnspan=3, sticky=tk.W+tk.E, padx=5, pady=5)

        # 按鈕區
        btn_box = ttk.Frame(form_grid)
        btn_box.grid(row=1, column=4, columnspan=4, sticky=tk.E, padx=5, pady=5)

        btn_save = ttk.Button(btn_box, text="💾 儲存/更新觸價單", style="Primary.TButton", command=self._on_click_save_rule)
        btn_save.pack(side=tk.LEFT, padx=5)

        btn_clear = ttk.Button(btn_box, text="🧹 清空輸入", command=self._clear_form)
        btn_clear.pack(side=tk.LEFT, padx=5)

    def _build_table_frame(self):
        """即時觸價監控清單表格"""
        card = ttk.LabelFrame(self, text=" 📊 即時股價觸價監控清單 (右鍵選單包含重置、測試與暫停功能) ", padding=8)
        card.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=4)

        # 建立 Treeview
        columns = ("code", "name", "last_price", "change", "upper_bound", "lower_bound", "status", "triggered_at", "note")
        self.tree = ttk.Treeview(card, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("code", text="代號 ⇅", command=lambda: self._cycle_sort_column("code"))
        self.tree.heading("name", text="股票名稱")
        self.tree.heading("last_price", text="即時成交價")
        self.tree.heading("change", text="漲跌 (幅%)")
        self.tree.heading("upper_bound", text="⬆️ 突破上界")
        self.tree.heading("lower_bound", text="⬇️ 跌破下界")
        self.tree.heading("status", text="監控狀態 ⇅", command=lambda: self._cycle_sort_column("status"))
        self.tree.heading("triggered_at", text="最後觸發時間")
        self.tree.heading("note", text="備註")

        self.tree.column("code", width=80, anchor=tk.CENTER)
        self.tree.column("name", width=120, anchor=tk.W)
        self.tree.column("last_price", width=110, anchor=tk.E)
        self.tree.column("change", width=120, anchor=tk.E)
        self.tree.column("upper_bound", width=110, anchor=tk.E)
        self.tree.column("lower_bound", width=110, anchor=tk.E)
        self.tree.column("status", width=90, anchor=tk.CENTER)
        self.tree.column("triggered_at", width=160, anchor=tk.CENTER)
        self.tree.column("note", width=200, anchor=tk.W)

        # 捲軸
        vsb = ttk.Scrollbar(card, orient="vertical", command=self._on_tree_yscroll)
        hsb = ttk.Scrollbar(card, orient="horizontal", command=self._on_tree_xscroll)
        self.tree.configure(
            yscrollcommand=lambda *args: (vsb.set(*args), self._update_all_cell_overlays()),
            xscrollcommand=lambda *args: (hsb.set(*args), self._update_all_cell_overlays())
        )

        self.tree.grid(row=0, column=0, sticky=tk.N+tk.S+tk.E+tk.W)
        vsb.grid(row=0, column=1, sticky=tk.N+tk.S)
        hsb.grid(row=1, column=0, sticky=tk.E+tk.W)

        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)

        # 標籤顏色樣式配置
        self.tree.tag_configure("ACTIVE", background="#FFFFFF", foreground="#000000")       # 平盤/預設黑色
        self.tree.tag_configure("PAUSED", background="#F0F0F0", foreground="#888888")
        self.tree.tag_configure("UPPER_TRIGGERED", background="#FFE6E6", foreground="#CC0000", font=("Microsoft JhengHei", 10, "bold"))
        self.tree.tag_configure("LOWER_TRIGGERED", background="#E6FFE6", foreground="#008000", font=("Microsoft JhengHei", 10, "bold"))
        self.tree.tag_configure("HOVER", background="#EBF5FB")  # 懸停柔和亮藍色

        # 事件綁定
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self.tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.tree.bind("<Configure>", lambda e: self._update_all_cell_overlays())

    def _build_log_frame(self):
        """觸發通知歷史日誌區塊"""
        card = ttk.LabelFrame(self, text=" 🔔 觸發通知即時紀錄 ", padding=8)
        card.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=8)

        log_cols = ("timestamp", "stock_code", "title", "message", "tg_status")
        self.log_tree = ttk.Treeview(card, columns=log_cols, show="headings", height=5)

        self.log_tree.heading("timestamp", text="時間")
        self.log_tree.heading("stock_code", text="個股")
        self.log_tree.heading("title", text="警示名稱")
        self.log_tree.heading("message", text="詳細訊息")
        self.log_tree.heading("tg_status", text="Telegram")

        self.log_tree.column("timestamp", width=150, anchor=tk.CENTER)
        self.log_tree.column("stock_code", width=80, anchor=tk.CENTER)
        self.log_tree.column("title", width=220, anchor=tk.W)
        self.log_tree.column("message", width=550, anchor=tk.W)
        self.log_tree.column("tg_status", width=90, anchor=tk.CENTER)

        log_vsb = ttk.Scrollbar(card, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=log_vsb.set)

        self.log_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 底部列按鈕
        btn_bar = ttk.Frame(card)
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=4)

        btn_test_toast = ttk.Button(btn_bar, text="🔔 測試桌面彈窗", command=self._on_test_toast)
        btn_test_toast.pack(side=tk.LEFT, padx=4)

        btn_test_tg = ttk.Button(btn_bar, text="📱 測試 Telegram", command=self._on_test_telegram)
        btn_test_tg.pack(side=tk.LEFT, padx=4)

        btn_clear_log = ttk.Button(btn_bar, text="🗑️ 清空日誌", command=self._clear_logs)
        btn_clear_log.pack(side=tk.RIGHT, padx=4)

    def _build_status_bar(self):
        """底部列狀態提示"""
        self.lbl_status_msg = ttk.Label(self, text="系統就緒", relief="sunken", anchor=tk.W, padding=3)
        self.lbl_status_msg.pack(side=tk.BOTTOM, fill=tk.X)

    def _create_context_menu(self):
        """右鍵選單功能」"""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="✏️ 載入至編輯區", command=self._on_menu_edit)
        self.context_menu.add_command(label="🔄 重置為監控中 (Reset)", command=self._on_menu_reset)
        self.context_menu.add_command(label="⏸️ 切換 啟用/暫停 (Pause)", command=self._on_menu_toggle_pause)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⬆️ 向上移動", command=lambda: self._on_menu_move("UP"))
        self.context_menu.add_command(label="⬇️ 向下移動", command=lambda: self._on_menu_move("DOWN"))
        self.context_menu.add_command(label="🔝 移至最頂部", command=lambda: self._on_menu_move("TOP"))
        self.context_menu.add_command(label="🔚 移至最底部", command=lambda: self._on_menu_move("BOTTOM"))
        self.context_menu.add_command(label="↺ 恢復自訂排序", command=self._reset_sort_to_custom)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⚡ 手動模擬價格突破測試", command=self._on_menu_mock_upper)
        self.context_menu.add_command(label="⚡ 手動模擬價格跌破測試", command=self._on_menu_mock_lower)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ 刪除此觸價單", command=self._on_menu_delete)

    # --- 內部事件與回呼邏輯 ---

    def _on_tick_received(self, code: str, price: float, change: float, change_rate: float):
        """來自 WebSocket 或 Mock 執行緒的 Tick 異步廣播」"""
        self.gui_queue.put(("TICK", (code, price, change, change_rate)))

    def _on_rule_updated(self, rule: TriggerRule, is_deleted: bool = False):
        """來自 TriggerEngine 的規則更新廣播"""
        self.gui_queue.put(("RULE_UPDATED", (rule, is_deleted)))

    def _on_notification_log_added(self, log_entry: Dict[str, Any], is_update: bool = False):
        """來自 Notifier 的通知紀錄廣播"""
        self.gui_queue.put(("LOG_UPDATED" if is_update else "LOG_ADDED", log_entry))

    def _start_network_monitor(self):
        """背景網路連線監控服務 Thread"""
        def monitor_loop():
            while not self._is_closing:
                connected = is_internet_available()
                if connected != self.is_network_connected:
                    self.is_network_connected = connected
                    self.gui_queue.put(("NETWORK_STATUS_CHANGED", connected))
                time.sleep(3.0)

        t = threading.Thread(target=monitor_loop, daemon=True)
        t.start()

    def _process_gui_queue(self):
        """主執行緒輪詢佇列並更新 Tkinter 元件"""
        try:
            while not self.gui_queue.empty():
                msg_type, data = self.gui_queue.get_nowait()
                if msg_type == "TICK":
                    code, price, change, change_rate = data
                    bypass = self.client.mock_running
                    self.engine.process_tick(code, price, change, change_rate, bypass_time_check=bypass)

                elif msg_type == "RULE_UPDATED":
                    rule, is_deleted = data
                    if is_deleted or rule.code not in self.engine.rules:
                        if rule.code in self._cell_labels:
                            self._cell_labels.pop(rule.code).destroy()
                        if self.tree.exists(rule.code):
                            self.tree.delete(rule.code)
                    else:
                        self._update_rule_in_treeview(rule)

                elif msg_type in ["LOG_ADDED", "LOG_UPDATED"]:
                    log_entry = data
                    self._add_or_update_log_in_treeview(log_entry)

                elif msg_type == "NETWORK_STATUS_CHANGED":
                    is_connected = data
                    if not is_connected:
                        self.lbl_api_status.config(text="🔴 網路中斷", bg="#DC3545", fg="#FFFFFF")
                        self.btn_login.config(text="🔄 點擊重連", style="Warning.TButton")
                        self.lbl_status_msg.config(text="⚠️ 偵測到網路連線中斷！請檢查網路連線後，點擊右上方 [🔄 點擊重連]。")
                        if not self.network_warned:
                            self.network_warned = True
                            self.notifier.notify(
                                title="網路連線中斷",
                                message="系統偵測到網路連線已中斷，觸價通知暫時失效！請恢復網路連線後點擊重連。",
                                stock_code="SYS",
                                trigger_type="SYSTEM"
                            )
                    else:
                        self.lbl_status_msg.config(text="✅ 網路連線已恢復，請點擊右上方 [🔄 點擊重連] 重新登入 API。")
                        self.btn_login.config(text="🔄 點擊重連", style="Warning.TButton")

        except Exception as e:
            logger.error(f"GUI 佇列處理異常: {e}")
        finally:
            self.after(100, self._process_gui_queue)

    def _update_rule_in_treeview(self, rule: TriggerRule):
        """將單筆 Rule 格式化更新至 Treeview」"""
        item_id = rule.code

        # 格式化顯示文字
        last_p_str = f"${rule.last_price:.2f}" if rule.last_price > 0 else "--"
        if rule.change > 0:
            change_str = f"🔺 +{rule.change:.2f} (+{rule.change_rate:.2f}%)"
        elif rule.change < 0:
            change_str = f"🔻 {rule.change:.2f} ({rule.change_rate:.2f}%)"
        else:
            change_str = "0.00 (0.00%)"

        upper_str = f"${rule.upper_bound:.2f}" if rule.upper_bound is not None else "--"
        lower_str = f"${rule.lower_bound:.2f}" if rule.lower_bound is not None else "--"

        status_display = rule.status
        tag = "ACTIVE"

        if rule.status == STATUS_PAUSED:
            status_display = "⏸️ 已暫停"
            tag = "PAUSED"
        elif rule.status == STATUS_TRIGGERED:
            if rule.triggered_type == "UPPER":
                status_display = "🔥 突破觸發"
                tag = "UPPER_TRIGGERED"
            elif rule.triggered_type == "LOWER":
                status_display = "❄️ 跌破觸發"
                tag = "LOWER_TRIGGERED"
            else:
                status_display = "⚡ 已觸發"
                tag = "UPPER_TRIGGERED"
        elif rule.status == STATUS_ACTIVE:
            status_display = "▶ 監控中"
            tag = "ACTIVE"

        trig_at_str = rule.triggered_at or "--"

        values = (
            rule.code,
            rule.name,
            last_p_str,
            "",  # 留空，由專屬 Label 覆蓋呈現獨立前景色 (避免影響其他欄位)
            upper_str,
            lower_str,
            status_display,
            trig_at_str,
            rule.note
        )

        if self.tree.exists(item_id):
            self.tree.item(item_id, values=values, tags=(tag,))
        else:
            self.tree.insert("", tk.END, iid=item_id, values=values, tags=(tag,))

        self._update_cell_overlay(item_id)

    def _add_or_update_log_in_treeview(self, log_entry: Dict[str, Any]):
        """新增或更新即時 Log 至下方紀錄表"""
        status = log_entry.get("telegram_status", "")
        if status == "SENT" or log_entry.get("telegram_sent"):
            tg_text = "✅ 已發送"
        elif status == "SENDING":
            tg_text = "⏳ 發送中..."
        elif status == "FAILED":
            tg_text = "❌ 發送失敗"
        elif status == "DISABLED":
            tg_text = "⏸️ 已關閉"
        elif status == "SYSTEM_ONLY":
            tg_text = "➖ 系統內部"
        else:
            tg_text = "➖ 未設定"

        values = (
            log_entry["timestamp"],
            log_entry["stock_code"],
            log_entry["title"],
            log_entry["message"].replace("\n", " | "),
            tg_text
        )

        log_id = log_entry.get("id")
        if log_id and self.log_tree.exists(log_id):
            self.log_tree.item(log_id, values=values)
        else:
            self.log_tree.insert("", 0, iid=log_id, values=values)

    def _reload_all_rules_in_ui(self):
        """刷新 Treeview 顯示所有已儲存規則 (若有臨時排序，僅影響當前顯示，不覆蓋 order_index)"""
        # 清除所有 cell labels
        for lbl in list(self._cell_labels.values()):
            lbl.destroy()
        self._cell_labels.clear()

        for item in self.tree.get_children():
            self.tree.delete(item)

        rules_list = list(self.engine.rules.values())

        if self.sort_state is None:
            rules_list.sort(key=lambda r: r.order_index)
        elif self.sort_state[0] == "code":
            rules_list.sort(key=lambda r: r.code, reverse=(self.sort_state[1] == "DESC"))
        elif self.sort_state[0] == "status":
            rules_list.sort(key=lambda r: r.status, reverse=(self.sort_state[1] == "DESC"))

        for rule in rules_list:
            self._update_rule_in_treeview(rule)
            # 自動訂閱
            self.client.subscribe(rule.code)

        self._update_all_cell_overlays()

    def _update_connection_status_ui(self):
        """更新頂部 API 與 Telegram 狀態燈標籤」"""
        if not self.is_network_connected:
            self.lbl_api_status.config(text="🔴 網路中斷", bg="#DC3545", fg="#FFFFFF")
            self.btn_login.config(text="🔄 點擊重連", style="Warning.TButton")
        elif self.client.is_logged_in:
            self.lbl_api_status.config(text="🟢 Shioaji: 已連線", bg="#28A745", fg="#FFFFFF")
            self.btn_login.config(text="🔑 登入 API", style="Primary.TButton")
        elif self.client.mock_running:
            self.lbl_api_status.config(text="🟡 模擬行情測試中", bg="#FFC107", fg="#000000")
            self.btn_login.config(text="🔑 登入 API", style="Primary.TButton")
        else:
            self.lbl_api_status.config(text="⚪ Shioaji: 離線", bg="#555555", fg="#FFFFFF")
            self.btn_login.config(text="🔑 登入 API", style="Primary.TButton")

        if not self.notifier.telegram_enabled:
            self.lbl_tg_status.config(text="⏸️ Telegram: 已關閉", bg="#555555", fg="#FFFFFF")
        elif self.notifier.telegram_token and self.notifier.telegram_chat_id:
            self.lbl_tg_status.config(text="🟢 Telegram: 已啟用", bg="#28A745", fg="#FFFFFF")
        else:
            self.lbl_tg_status.config(text="⚪ Telegram: 未設定", bg="#555555", fg="#FFFFFF")

    def _on_toggle_tg_enable(self):
        """切換 Telegram 推播開關」"""
        enabled = self.var_tg_enable.get()
        self.notifier.set_telegram_config(
            self.notifier.telegram_token,
            self.notifier.telegram_chat_id,
            enabled=enabled,
            save_to_env=True
        )
        self._update_connection_status_ui()
        status_str = "已啟用" if enabled else "已關閉"
        self.lbl_status_msg.config(text=f"Telegram 推播已切換為：【{status_str}】(已自動同步寫入 .env)。")

    # --- 使用者互動與動作處理 ---

    def _auto_start(self):
        """嘗試登入，若離線則啟動 Mock 行情讓使用者開箱即可測試"""
        success = self.client.login()
        if not success:
            self.lbl_status_msg.config(text="未偵測到有效的 Shioaji API KEY，已自動開啟模擬行情測試模式。")
            self.client.start_mock_ticks()
            self.btn_mock.config(text="⏹️ 停止模擬行情")
        else:
            self.lbl_status_msg.config(text="Shioaji API 登入成功，正在即時接收盤中行情...")
            # 重新訂閱
            for code in self.engine.rules.keys():
                self.client.subscribe(code)
        
        self._update_connection_status_ui()

    def _on_code_focus_out(self, event=None):
        """輸入股票代號後自動查詢股票名稱"""
        code = self.ent_code.get().strip().upper()
        if code:
            info = self.client.get_stock_info(code)
            self.ent_name.delete(0, tk.END)
            self.ent_name.insert(0, info.get("name", code))

    def _on_click_save_rule(self):
        """點擊 [儲存/更新觸價單]"""
        code = self.ent_code.get().strip().upper()
        name = self.ent_name.get().strip()
        upper_raw = self.ent_upper.get().strip()
        lower_raw = self.ent_lower.get().strip()
        note = self.ent_note.get().strip()

        if not code:
            messagebox.showwarning("欄位缺失", "請輸入股票代號！")
            return

        upper_val = None
        lower_val = None

        if upper_raw:
            try:
                upper_val = float(upper_raw)
            except ValueError:
                messagebox.showerror("格式錯誤", "價格上界必須為數字！")
                return

        if lower_raw:
            try:
                lower_val = float(lower_raw)
            except ValueError:
                messagebox.showerror("格式錯誤", "價格下界必須為數字！")
                return

        if upper_val is None and lower_val is None:
            messagebox.showwarning("欄位缺失", "請至少設定一個【價格上界】或【價格下界】！")
            return

        if upper_val is not None and lower_val is not None and lower_val >= upper_val:
            messagebox.showwarning("條件不合理", "價格下界 (跌破價) 應該小於價格上界 (突破價)！")
            return

        # 儲存
        rule = self.engine.add_or_update_rule(
            code=code,
            name=name,
            upper_bound=upper_val,
            lower_bound=lower_val,
            note=note
        )

        # 向 Client 訂閱行情
        self.client.subscribe(code)

        self._clear_form()
        self.lbl_status_msg.config(text=f"已成功設定 [{code} {rule.name}] 的觸價條件！")

        # 欄位閃爍高亮動畫效果 (如同滑鼠點擊)
        self._flash_item_in_treeview(code)

    def _flash_item_in_treeview(self, item_id: str):
        """
        儲存或更新觸價單時，讓該列閃爍高亮 (模擬滑鼠點擊視覺效果)
        """
        if not self.tree.exists(item_id):
            return

        # 滾動定位並高亮選取
        self.tree.see(item_id)
        self.tree.selection_set(item_id)
        self._update_all_cell_overlays()

        if self._selection_timer:
            self.after_cancel(self._selection_timer)
            self._selection_timer = None

        def step2():
            if self.tree.exists(item_id):
                self.tree.selection_remove(item_id)
                self._update_all_cell_overlays()

        def step3():
            if self.tree.exists(item_id):
                self.tree.selection_set(item_id)
                self._update_all_cell_overlays()
                self._selection_timer = self.after(2000, self._auto_deselect_tree)

        self.after(200, step2)
        self.after(400, step3)

    def _clear_form(self):
        """清空輸入欄位"""
        self.ent_code.delete(0, tk.END)
        self.ent_name.delete(0, tk.END)
        self.ent_upper.delete(0, tk.END)
        self.ent_lower.delete(0, tk.END)
        self.ent_note.delete(0, tk.END)

    def _on_click_login(self):
        """手動觸發 API 登入與網路重連」"""
        if not is_internet_available():
            messagebox.showerror("網路中斷", "目前網路連線仍未恢復，請先檢查 Wi-Fi 或網路連線狀態！")
            return

        self.lbl_status_msg.config(text="正在重新連線 Shioaji API 並恢復行情訂閱...")
        success = self.client.login()
        if success:
            for code in self.engine.rules.keys():
                self.client.subscribe(code)
            messagebox.showinfo("連線成功", "Shioaji API 登入/重連成功！已恢復即時行情監控。")
            self.lbl_status_msg.config(text="✅ 重新連線成功！即時行情已恢復監控。")
            self.network_warned = False
            self.notifier.notify(
                title="網路連線恢復",
                message="Shioaji API 重新登入成功，即時行情觸價監控已全面恢復！",
                stock_code="SYS",
                trigger_type="SYSTEM"
            )
        else:
            messagebox.showerror("登入失敗", "Shioaji API 登入失敗！請確認 .env 設定與 API KEY。")
        self._update_connection_status_ui()

    def _on_toggle_mock(self):
        """開關模擬行情測試」"""
        if self.client.mock_running:
            self.client.stop_mock_ticks()
            self.btn_mock.config(text="🧪 啟動模擬行情")
            self.lbl_status_msg.config(text="已停止模擬行情。")
        else:
            # 確保已知股票都有在 mock 設定中
            for code in self.engine.rules.keys():
                self.client.subscribe(code)
            self.client.start_mock_ticks()
            self.btn_mock.config(text="⏹️ 停止模擬行情")
            self.lbl_status_msg.config(text="已啟動模擬行情發送器。")
        self._update_connection_status_ui()

    def _on_click_tg_config(self):
        """動態設定 Telegram Bot」"""
        curr_token = self.notifier.telegram_token
        curr_chat = self.notifier.telegram_chat_id

        new_token = simpledialog.askstring("Telegram Bot Token", "請輸入 Telegram Bot Token:", initialvalue=curr_token)
        if new_token is None:
            return

        new_chat = simpledialog.askstring("Telegram Chat ID", "請輸入 Telegram Chat ID (例如 12345678):", initialvalue=curr_chat)
        if new_chat is None:
            return

        self.notifier.set_telegram_config(new_token.strip(), new_chat.strip(), save_to_env=True)
        self._update_connection_status_ui()
        messagebox.showinfo("設定更新", "Telegram Bot 設定已更新並自動儲存至 .env！下次開機時將自動載入。")

    def _on_test_toast(self):
        """測試桌面彈窗」"""
        self.notifier.notify(
            title="測試通知 [2330 台積電]",
            message="這是一條測試桌面彈窗與聲響通知訊息！",
            stock_code="2330",
            trigger_type="TEST"
        )

    def _on_test_telegram(self):
        """測試 Telegram 推播」"""
        if not self.notifier.telegram_token or not self.notifier.telegram_chat_id:
            messagebox.showwarning("尚未設定", "請先點擊上方「Telegram 設定」輸入 Token 與 Chat ID！")
            return

        self.notifier.notify(
            title="測試 Telegram 觸價推播",
            message="恭喜！您的 Telegram Bot 已成功串接 Shioaji 股價觸價通知系統！",
            stock_code="TEST",
            trigger_type="TEST"
        )

    def _clear_logs(self):
        """清空通知紀錄」"""
        for item in self.log_tree.get_children():
            self.log_tree.delete(item)

    # --- 右鍵與表格互動 ---

    def _on_tree_select(self, event=None):
        """當點擊選取某一列時，啟動無操作自動復原計時器"""
        if self._selection_timer:
            self.after_cancel(self._selection_timer)
            self._selection_timer = None

        # 點擊高亮後，2.5 秒無操作自動取消高亮，改回原本顏色
        self._selection_timer = self.after(2500, self._auto_deselect_tree)

    def _auto_deselect_tree(self):
        """無操作後自動取消高亮選取，回復原本狀態顏色"""
        try:
            selected = self.tree.selection()
            if selected:
                self.tree.selection_remove(selected)
        except Exception:
            pass
        self._selection_timer = None

    def _on_tree_motion(self, event):
        """滑鼠懸停 (Hover) 於某一列時動態高亮，滑過後改回"""
        item = self.tree.identify_row(event.y)
        if item != self._hover_item:
            # 復原舊列
            if self._hover_item and self.tree.exists(self._hover_item):
                rule = self.engine.rules.get(self._hover_item)
                if rule:
                    self._update_rule_in_treeview(rule)

            self._hover_item = item
            if item and self.tree.exists(item):
                # 取得該列當前 tags 並加入 HOVER 樣式
                curr_tags = list(self.tree.item(item, "tags"))
                if "HOVER" not in curr_tags:
                    curr_tags.append("HOVER")
                    self.tree.item(item, tags=curr_tags)

    def _on_tree_leave(self, event=None):
        """滑鼠離開表格區域時復原最後懸停列"""
        if self._hover_item and self.tree.exists(self._hover_item):
            rule = self.engine.rules.get(self._hover_item)
            if rule:
                self._update_rule_in_treeview(rule)
        self._hover_item = None

    def _on_tree_double_click(self, event):
        """雙擊表格列：快速切換 監控中 / 已暫停 狀態 (若已觸發則重置為監控中)"""
        code = self.tree.identify_row(event.y)
        if not code:
            code = self._get_selected_code()

        if code and code in self.engine.rules:
            rule = self.engine.rules[code]
            if rule.status == STATUS_TRIGGERED:
                self.engine.reset_trigger(code)
                self.lbl_status_msg.config(text=f"已重置 [{code}] 狀態為【▶ 監控中】。")
            else:
                self.engine.toggle_pause(code)
                new_status = self.engine.rules[code].status
                status_name = "【⏸️ 已暫停】" if new_status == STATUS_PAUSED else "【▶ 監控中】"
                self.lbl_status_msg.config(text=f"已切換 [{code}] 狀態為 {status_name}。")

    def _on_tree_right_click(self, event):
        """右鍵彈出選單」"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def _get_selected_code(self) -> Optional[str]:
        selected = self.tree.selection()
        if selected:
            return selected[0]
        return None

    def _on_menu_edit(self):
        code = self._get_selected_code()
        if code and code in self.engine.rules:
            rule = self.engine.rules[code]
            self.ent_code.delete(0, tk.END)
            self.ent_code.insert(0, rule.code)
            self.ent_name.delete(0, tk.END)
            self.ent_name.insert(0, rule.name)
            self.ent_upper.delete(0, tk.END)
            if rule.upper_bound is not None:
                self.ent_upper.insert(0, str(rule.upper_bound))
            self.ent_lower.delete(0, tk.END)
            if rule.lower_bound is not None:
                self.ent_lower.insert(0, str(rule.lower_bound))
            self.ent_note.delete(0, tk.END)
            self.ent_note.insert(0, rule.note)

    def _on_menu_reset(self):
        code = self._get_selected_code()
        if code:
            self.engine.reset_trigger(code)
            self.lbl_status_msg.config(text=f"已重置 [{code}] 狀態為【🟢 監控中】。")

    def _on_menu_toggle_pause(self):
        code = self._get_selected_code()
        if code:
            self.engine.toggle_pause(code)

    def _on_drag_start(self, event):
        """開始拖曳」"""
        item = self.tree.identify_row(event.y)
        if item:
            self._drag_item = item

    def _on_drag_motion(self, event):
        """拖曳過程中視覺移動列」"""
        if self._drag_item:
            target = self.tree.identify_row(event.y)
            if target and target != self._drag_item:
                target_idx = self.tree.index(target)
                self.tree.move(self._drag_item, "", target_idx)

    def _on_drag_release(self, event):
        """放開拖曳時，退出臨時檢視模式並將 Treeview 順序儲存為新的自訂順序」"""
        if self._drag_item:
            current_codes = list(self.tree.get_children())
            self.engine.reorder_by_codes(current_codes)
            self._drag_item = None
            self.sort_state = None  # 切換回自訂模式
            self._update_heading_labels()
            self._on_tree_select(event)

    def _on_menu_move(self, direction: str):
        """右鍵選單調整順序 (自動切換回自訂模式)」"""
        code = self._get_selected_code()
        if code:
            self.sort_state = None
            self._update_heading_labels()
            success = self.engine.move_rule(code, direction)
            if success:
                self._reload_all_rules_in_ui()
                self.tree.selection_set(code)

    def _on_menu_mock_upper(self):
        """手動注入突破價」"""
        code = self._get_selected_code()
        if code and code in self.engine.rules:
            rule = self.engine.rules[code]
            target_price = (rule.upper_bound or 100.0) + 5.0
            self.client.trigger_manual_mock_tick(code, target_price)

    def _on_menu_mock_lower(self):
        """手動注入跌破價」"""
        code = self._get_selected_code()
        if code and code in self.engine.rules:
            rule = self.engine.rules[code]
            target_price = (rule.lower_bound or 100.0) - 5.0
            self.client.trigger_manual_mock_tick(code, target_price)

    def _on_menu_delete(self):
        code = self._get_selected_code()
        if code:
            confirm = messagebox.askyesno("刪除確認", f"確定要刪除 [{code}] 的觸價設定嗎？")
            if confirm:
                self.client.unsubscribe(code)
                if self.tree.exists(code):
                    self.tree.delete(code)
                self.engine.remove_rule(code)
                self.lbl_status_msg.config(text=f"已刪除 [{code}] 觸價設定。")

    def _cycle_sort_column(self, col: str):
        """
        三階段標頭排序循環 (Plan A):
        階段 1: 升冪 (ASC ⬆)
        階段 2: 降冪 (DESC ⬇)
        階段 3: 恢復手動自訂順序 (NONE ↺)
        """
        if col not in ["code", "status"]:
            return

        if self.sort_state == (col, "ASC"):
            self.sort_state = (col, "DESC")
        elif self.sort_state == (col, "DESC"):
            self.sort_state = None  # 回覆自訂
        else:
            self.sort_state = (col, "ASC")

        self._update_heading_labels()
        self._reload_all_rules_in_ui()

    def _reset_sort_to_custom(self):
        """手動一鍵恢復為原本拖曳/排序好的自訂順序"""
        self.sort_state = None
        self._update_heading_labels()
        self._reload_all_rules_in_ui()
        self.lbl_status_msg.config(text="已恢復為手動自訂排序順序。")

    def _update_heading_labels(self):
        """依據當前臨時檢視狀態動態更新欄位標頭文字提示"""
        code_text = "代號 ⇅"
        status_text = "監控狀態 ⇅"

        if self.sort_state == ("code", "ASC"):
            code_text = "代號 ⬆ (點擊切換降冪)"
        elif self.sort_state == ("code", "DESC"):
            code_text = "代號 ⬇ (點擊恢復自訂)"
        elif self.sort_state == ("status", "ASC"):
            status_text = "監控狀態 ⬆ (點擊切換降冪)"
        elif self.sort_state == ("status", "DESC"):
            status_text = "監控狀態 ⬇ (點擊恢復自訂)"

        self.tree.heading("code", text=code_text)
        self.tree.heading("status", text=status_text)

    def _on_tree_yscroll(self, *args):
        self.tree.yview(*args)
        self._update_all_cell_overlays()

    def _on_tree_xscroll(self, *args):
        self.tree.xview(*args)
        self._update_all_cell_overlays()

    def _update_cell_overlay(self, item_id: str):
        """更新「漲跌 (幅%)」單一欄位的獨立文字色彩標籤 (不影響其他欄位純黑文字)"""
        if not self.tree.exists(item_id):
            if item_id in self._cell_labels:
                self._cell_labels.pop(item_id).destroy()
            return

        rule = self.engine.rules.get(item_id)
        if not rule:
            return

        # 確定前景色
        if rule.change > 0:
            fg_color = "#CC0000"  # 上漲純紅字
            change_str = f"▲ +{rule.change:.2f} (+{rule.change_rate:.2f}%)"
        elif rule.change < 0:
            fg_color = "#008000"  # 下跌純綠字
            change_str = f"▼ {rule.change:.2f} ({rule.change_rate:.2f}%)"
        else:
            fg_color = "#000000"  # 平盤純黑字
            change_str = "0.00 (0.00%)"

        # 確定背景色 (依據項目狀態)
        bg_color = "#FFFFFF"
        if rule.status == STATUS_PAUSED:
            bg_color = "#F0F0F0"
        elif rule.status == STATUS_TRIGGERED:
            bg_color = "#FFE6E6" if rule.triggered_type == "UPPER" else "#E6FFE6"

        if item_id == self._hover_item:
            bg_color = "#EBF5FB"

        self.update_idletasks()
        bbox = self.tree.bbox(item_id, "change")
        if not bbox or len(bbox) < 4 or bbox[2] <= 0:
            if item_id in self._cell_labels:
                self._cell_labels[item_id].place_forget()
            return

        x, y, w, h = bbox

        if item_id not in self._cell_labels:
            lbl = tk.Label(self.tree, anchor=tk.E, padx=6)
            # 事件綁定：點擊覆蓋 Label 時轉發至 Treeview
            lbl.bind("<Double-1>", lambda e, code=item_id: self._on_cell_double_click(e, code))
            lbl.bind("<Button-3>", lambda e, code=item_id: self._on_cell_right_click(e, code))
            lbl.bind("<ButtonPress-1>", lambda e, code=item_id: self._on_cell_click(e, code))
            lbl.bind("<B1-Motion>", self._on_drag_motion)
            lbl.bind("<ButtonRelease-1>", self._on_drag_release)
            lbl.bind("<Motion>", lambda e, code=item_id: self._on_cell_motion(e, code))
            lbl.bind("<Leave>", self._on_tree_leave)
            self._cell_labels[item_id] = lbl
        else:
            lbl = self._cell_labels[item_id]

        lbl.config(text=change_str, fg=fg_color, bg=bg_color, font=("Microsoft JhengHei", 9, "bold"))
        lbl.place(x=x, y=y, width=w, height=h)

    def _update_all_cell_overlays(self):
        """重新調整所有漲跌幅欄位標籤的位置與色彩」"""
        for item_id in list(self.engine.rules.keys()):
            self._update_cell_overlay(item_id)

    def _on_cell_click(self, event, code: str):
        if self.tree.exists(code):
            self.tree.selection_set(code)
            self._on_tree_select(event)
            self._on_drag_start(event)

    def _on_cell_double_click(self, event, code: str):
        if self.tree.exists(code):
            self.tree.selection_set(code)
            self._on_tree_double_click(event)

    def _on_cell_right_click(self, event, code: str):
        if self.tree.exists(code):
            self.tree.selection_set(code)
            self.context_menu.post(event.x_root, event.y_root)

    def _on_cell_motion(self, event, code: str):
        fake_event = type("Event", (), {"y": self.tree.bbox(code, "change")[1] if self.tree.exists(code) and self.tree.bbox(code, "change") else 0})()
        self._on_tree_motion(fake_event)

    def on_closing(self):
        """完全關閉應用程式與清除執行緒」"""
        self._is_closing = True
        try:
            self.client.stop_mock_ticks()
            self.engine.save_to_storage()
        except Exception:
            pass
        self.destroy()
        os._exit(0)
