"""
Main Application Entry Point
永豐金 Shioaji 即時股價觸價通知系統 GUI 主入口。
"""
import sys
import logging
from dotenv import load_dotenv

# 載入 .env 環境變數
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 全局唯一 Mutex 名稱 (防止重複開啟)
MUTEX_NAME = "Global\\ShioajiTriggerAlertSystem_SingleInstanceMutex_v1"
_mutex = None

def check_single_instance():
    """檢查是否已有同名程式在執行中，避免重複開啟多個實體進程"""
    global _mutex
    if sys.platform == "win32":
        try:
            import ctypes
            import tkinter as tk
            from tkinter import messagebox

            kernel32 = ctypes.windll.kernel32
            _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
            last_error = kernel32.GetLastError()
            ERROR_ALREADY_EXISTS = 183

            if last_error == ERROR_ALREADY_EXISTS:
                logger.warning("偵測到【Shioaji 即時股價觸價通知系統】已有實體在執行中，防止重複開啟第二個進程。")
                root = tk.Tk()
                root.withdraw()
                messagebox.showwarning(
                    "重複開啟警告",
                    "【Shioaji 即時股價觸價通知系統】已經在執行中！\n\n請直接使用已在工作列或桌面運作的視窗，無需重複點擊。"
                )
                root.destroy()
                sys.exit(0)
        except Exception as e:
            logger.warning(f"單實體進程鎖檢查非致命例外: {e}")

from src.gui import MainGUI

def main():
    # 防止重複開啟第二個實體
    check_single_instance()

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("shioaji.trigger.alert.gui.v1")
        except Exception:
            pass

    logger.info("正在啟動 永豐金 Shioaji 即時股價觸價通知系統 GUI...")
    try:
        app = MainGUI()
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("接收到中斷訊號，正在關閉系統...")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"應用程式執行發生致命例外: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
