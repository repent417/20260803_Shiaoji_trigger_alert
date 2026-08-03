# 永豐金 Shioaji 即時股價觸價通知系統 GUI (Shioaji Price Trigger Notifier)

基於 Python + Tkinter + 永豐金 Shioaji API 開發的桌面即時台股觸價監控與通知系統。

---

## 🌟 核心功能特色

1. **即時股價 Touch-Price 觸價監控**：
   - 支援個股設定 **突破上界 (Upper Bound)** 與 **跌破下界 (Lower Bound)**。
   - 連結 永豐金 Shioaji WebSocket 即時 Tick 行情，毫秒級比對。
2. **三重即時通知機制**：
   - **Windows 桌面彈窗 (Toast Notification)**：即時跳出桌面通知視窗與個股資訊。
   - **系統警示音效 (Audio Beep)**：觸價第一時間播放警告聲響。
   - **Telegram Bot 推播**：整合 Telegram API，設定 Token 與 Chat ID 後即時推播至手機。
   - **GUI 高亮與歷史紀錄 (Visual Flash & Log)**：視窗表格自動橘紅/綠色高亮，並寫入觸發歷史區。
3. **安全防重複警報 (Cool-down / State Machine)**：
   - 觸價成功後自動切換為 `Triggered` 狀態，避免連續成交引發頻繁重複推播。
   - 支援右鍵選單一鍵 `重置為監控中 (Reset)`。
4. **離線與模擬行情測試器 (Mock Simulator)**：
   - 盤後或無 API Key 時，內建模擬行情波動發送器。
   - 支援右鍵「手動注入突破價/跌破價」，方便驗證通知運作。
5. **持久化紀錄 (Persistent Storage)**：
   - 所有個股觸價設定自動儲存至 `data/alert_rules.json`，重新啟動系統自動恢復。

---

## 📁 專案目錄結構

```text
20260803_Shiaoji_觸價通知/
├── .env                  # 環境變數設定檔 (金鑰與 Telegram 參數)
├── .env.template         # 環境變數範本檔
├── .gitignore            # Git 忽略檔
├── README.md             # 說明文件
├── requirements.txt      # Python 依賴包列表
├── main.py               # 程式主要入口
├── data/
│   └── alert_rules.json  # 本地選單與觸價條件儲存檔
└── src/
    ├── __init__.py
    ├── client.py         # Shioaji API 登入、行情訂閱與 Mock 產生器
    ├── gui.py            # Tkinter 桌面 GUI 介面與事件佇列
    ├── notifier.py       # Toast / 音效 / Telegram 通知引擎
    ├── storage.py        # JSON 存取管理器
    └── trigger_engine.py # 觸價狀態機與比對邏輯
```

---

## 🚀 快速開始步驟

### 1. 安裝套件
請於 Terminal 執行：
```bash
pip install -r requirements.txt
```

### 2. 設定 `.env` 環境變數
複製 `.env.template` 並命名為 `.env`：
```env
# 永豐金 Shioaji API
API_KEY=YOUR_API_KEY
SECRET_KEY=YOUR_SECRET_KEY
PERSON_ID=YOUR_PERSON_ID
SIMULATION=True

# Telegram Bot (可選)
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_CHAT_ID
```

> **💡 如何建立 Telegram Bot 與取得 Chat ID？**
> 1. 在 Telegram 搜尋 `@BotFather` 並傳送 `/newbot` 依提示建立 Bot，獲取 **Bot Token**。
> 2. 將新 Bot 加入您的個人對話或群組。
> 3. 在 Telegram 搜尋 `@userinfobot` 傳送隨意訊息即可獲取您的 **Chat ID**。

### 3. 啟動系統
```bash
python main.py
```

---

## 🖥️ 使用指引

1. **新增觸價單**：
   - 輸入股票代號 (例 `2330`)，系統自動帶出名稱 (`台積電`)。
   - 輸入「價格上界」(突破通知) 或「價格下界」(跌破通知)。
   - 點選 **💾 儲存/更新觸價單**。
2. **測試觸價通知**：
   - 於表格中對個股按**右鍵**，選擇 `⚡ 手動模擬價格突破測試` 或 `⚡ 手動模擬價格跌破測試`。
   - 您將同時收到桌面 Toast 通知、警告音效與 Telegram 訊息 (若有設定)。
3. **重置觸發狀態**：
   - 觸價後的項目會標示為 `🔥 突破觸發` 或 `❄️ 跌破觸發`。
   - 對項目按**右鍵**選擇 `🔄 重置為監控中 (Reset)` 即可重新開始監控。
