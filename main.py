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

from src.gui import MainGUI

def main():
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
