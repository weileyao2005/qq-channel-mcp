"""
QQ频道增量同步脚本
- 读取上次同步位置，只拉新增帖子
- 写入本地 SQLite
- 可选：检查关键词，记录命中
用法:
    python sync_once.py            增量同步
    python sync_once.py --full     回补最近 2 天
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from qq_client import QQChannelClient  # noqa: E402
import cache  # noqa: E402

LOG = os.path.join(BASE, "sync.log")
CONFIG = os.path.join(BASE, "config.json")

# 监听关键词：命中后写进 watch_hits（避免单字，减少误报）
WATCH_KEYWORDS = [
    "失物", "捡到", "丢了一", "寻找失主", "拼车", "兼职", "招聘",
    "出一", "收一", "求购", "求推荐", "组队", "青马", "青苗",
]


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_cfg():
    return json.load(open(CONFIG, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="回补最近2天")
    ap.add_argument("--days", type=float, default=2.0, help="回补天数（配合 --full）")
    args = ap.parse_args()

    cfg = load_cfg()
    c = QQChannelClient(cfg["cookie"], cfg["guild_id"], cfg["guild_number"])

    last = cache.get_state("last_sync_ts")
    now = int(time.time())

    if args.full or not last:
        since = now - int(args.days * 86400)
        mode = f"回补 {args.days} 天"
    else:
        # 从上次位置继续（覆盖关机期间），往前 10 分钟防边界漏帖；
        # 最多回溯 30 天，避免关机太久时拉太多
        since = max(int(last) - 600, now - 30 * 86400)
        gap_h = (now - int(last)) / 3600
        mode = f"增量（距上次 {gap_h:.1f} 小时）"

    log(f"开始同步（{mode}），since={datetime.fromtimestamp(since):%Y-%m-%d %H:%M}")

    try:
        feeds = c.get_timeline_feeds("635029104", since_ts=since, limit=8000, max_pages=600)
    except Exception as e:
        msg = str(e)
        if "登录态" in msg or "10006" in msg:
            log(f"❌ 登录态已过期，需要更新 config.json 的 cookie：{msg}")
            cache.set_state("last_auth_error", datetime.now().isoformat())
        else:
            log(f"同步失败: {type(e).__name__}: {msg}")
        return 1

    if not feeds:
        log("没有新帖子")
        cache.set_state("last_sync_ts", now)
        return 0

    n = cache.upsert_feeds(feeds)
    cache.set_state("last_sync_ts", now)

    # 关键词监听
    hits = []
    for f in feeds:
        text = f.get("text") or ""
        for kw in WATCH_KEYWORDS:
            if kw in text:
                hits.append((kw, f))
                break
    if hits:
        con = cache.connect()
        for kw, f in hits:
            try:
                con.execute(
                    "INSERT OR IGNORE INTO watch_hits(feed_id, keyword, author, text, create_time, notified) VALUES(?,?,?,?,?,0)",
                    (f["feed_id"], kw, (f.get("author") or {}).get("nick"), (f.get("text") or "")[:200], f.get("create_time")),
                )
            except Exception:
                pass
        con.commit()
        con.close()
        log(f"关键词命中 {len(hits)} 条")

    st = cache.stats()
    log(f"同步完成: 拉到 {len(feeds)} 条，库内共 {st['total']} 条，"
        f"范围 {datetime.fromtimestamp(st['oldest'] or 0):%m-%d %H:%M} ~ {datetime.fromtimestamp(st['newest'] or 0):%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
