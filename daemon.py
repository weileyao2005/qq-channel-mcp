"""
常驻守护：登录后启动，每小时增量同步一次
- 由注册表 HKCU\\...\\Run 启动
- 崩溃自动恢复
"""
import os
import sys
import time
import traceback
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

LOG = os.path.join(BASE, "daemon.log")
INTERVAL = 5 * 3600  # 5 小时


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_once():
    try:
        import sync_once
        sync_once.main()
    except SystemExit:
        pass
    except Exception:
        log("同步异常:\n" + traceback.format_exc())
    try:
        import daily_digest
        daily_digest.main()
    except SystemExit:
        pass
    except Exception:
        log("精选异常:\n" + traceback.format_exc())


def main():
    log("守护启动")
    while True:
        run_once()
        log(f"等待 {INTERVAL}s 后下一轮")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
