"""
本地缓存：把频道帖子存 SQLite，查询走本地，避免反复爬服务器
"""
import json
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feeds.db")


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS feeds (
            feed_id      TEXT PRIMARY KEY,
            author_id    TEXT,
            author_nick  TEXT,
            level        TEXT,
            role         TEXT,
            text         TEXT,
            create_time  INTEGER,
            likes        INTEGER,
            comments     INTEGER,
            shares       INTEGER,
            channel      TEXT,
            channel_id   TEXT,
            guild_id     TEXT,
            collects     INTEGER DEFAULT 0,
            raw          TEXT,
            synced_at    INTEGER
        )
    """)
    # 兼容旧库：补列
    try:
        con.execute("ALTER TABLE feeds ADD COLUMN collects INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    con.execute("CREATE INDEX IF NOT EXISTS idx_feeds_ct ON feeds(create_time)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_feeds_author ON feeds(author_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_feeds_nick ON feeds(author_nick)")
    con.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS watch_hits (
            feed_id     TEXT,
            keyword     TEXT,
            author      TEXT,
            text        TEXT,
            create_time INTEGER,
            notified    INTEGER DEFAULT 0,
            PRIMARY KEY (feed_id, keyword)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS classified (
            feed_id        TEXT PRIMARY KEY,
            category       TEXT,
            reason         TEXT,
            model          TEXT,
            classified_at  INTEGER
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_classified_cat ON classified(category)")
    return con


def unclassified(limit=3000):
    """取还没有分类过的帖子"""
    con = connect()
    rows = con.execute("""
        SELECT f.* FROM feeds f
        LEFT JOIN classified c ON f.feed_id = c.feed_id
        WHERE c.feed_id IS NULL
        ORDER BY f.create_time DESC
        LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def save_classifications(items, model="deepseek-chat"):
    """items: [(feed_id, category, reason)]"""
    con = connect()
    now = int(time.time())
    for fid, cat, reason in items:
        con.execute("""
            INSERT INTO classified(feed_id, category, reason, model, classified_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(feed_id) DO UPDATE SET
                category=excluded.category, reason=excluded.reason,
                model=excluded.model, classified_at=excluded.classified_at
        """, (fid, cat, reason, model, now))
    con.commit()
    con.close()
    return len(items)


def classified_stats():
    con = connect()
    rows = con.execute("SELECT category, COUNT(*) FROM classified GROUP BY category").fetchall()
    con.close()
    return {r[0]: r[1] for r in rows}


def upsert_feeds(feeds):
    con = connect()
    now = int(time.time())
    n = 0
    for f in feeds:
        a = f.get("author") or {}
        con.execute("""
            INSERT INTO feeds (feed_id, author_id, author_nick, level, role, text, create_time,
                               likes, comments, shares, channel, channel_id, guild_id, collects, raw, synced_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(feed_id) DO UPDATE SET
                likes=excluded.likes, comments=excluded.comments, shares=excluded.shares,
                collects=excluded.collects, text=excluded.text, raw=excluded.raw, synced_at=excluded.synced_at
        """, (
            f.get("feed_id"), a.get("id"), a.get("nick"), a.get("level"), a.get("role"),
            f.get("text"), f.get("create_time"), f.get("likes"), f.get("comments"),
            f.get("shares"), f.get("channel"), f.get("channel_id"), f.get("guild_id"),
            f.get("collects", 0), json.dumps(f, ensure_ascii=False), now
        ))
        n += 1
    con.commit()
    con.close()
    return n


def query(keyword=None, author=None, days=None, limit=50, order="time"):
    con = connect()
    sql = "SELECT * FROM feeds WHERE 1=1"
    args = []
    if author:
        sql += " AND (author_id = ? OR author_nick LIKE ?)"
        args += [author, f"%{author}%"]
    if keyword:
        sql += " AND text LIKE ?"
        args.append(f"%{keyword}%")
    if days:
        sql += " AND create_time >= ?"
        args.append(int(time.time() - days * 86400))
    order_sql = "ORDER BY likes DESC" if order == "hot" else "ORDER BY create_time DESC"
    sql += f" {order_sql} LIMIT ?"
    args.append(limit)
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    total = con.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
    con.close()
    return rows, total


def get_feed(feed_id):
    con = connect()
    row = con.execute("SELECT * FROM feeds WHERE feed_id=?", (feed_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def stats():
    con = connect()
    total = con.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
    lo = con.execute("SELECT MIN(create_time) FROM feeds").fetchone()[0]
    hi = con.execute("SELECT MAX(create_time) FROM feeds").fetchone()[0]
    users = con.execute("SELECT COUNT(DISTINCT author_id) FROM feeds").fetchone()[0]
    con.close()
    return {"total": total, "oldest": lo, "newest": hi, "users": users}


def get_state(key):
    con = connect()
    row = con.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    con.close()
    return row["value"] if row else None


def set_state(key, value):
    con = connect()
    con.execute("INSERT INTO sync_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))
    con.commit()
    con.close()
