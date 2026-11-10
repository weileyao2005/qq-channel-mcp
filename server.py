"""
QQ频道 MCP Server
只读能力走纯 HTTP（游客态也能用），写能力目前仅点赞（无需图灵签名）。
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))
from qq_client import QQChannelClient, QQChannelError  # noqa: E402
import cache  # noqa: E402

CONFIG_PATH = Path(__file__).parent / "config.json"

mcp = FastMCP("qq-channel")


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_client():
    cfg = load_config()
    return QQChannelClient(
        cookie=cfg.get("cookie", ""),
        guild_id=cfg.get("guild_id", ""),
        guild_number=cfg.get("guild_number", ""),
    )


def fmt_time(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def fmt_short(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def _feed_line(f):
    a = f["author"] if "author" in f else {"nick": f.get("author_nick"), "level": f.get("level"), "role": f.get("role")}
    role = f" [{a['role']}]" if a.get("role") else ""
    return (f"[{fmt_short(f['create_time'])}] {a.get('nick')} lv{a.get('level') or '?'}{role}"
            f" · {f['channel']} · 👍{f['likes']}💬{f['comments']}🔁{f['shares']}⭐{f.get('collects', 0)}"
            f" · {f['feed_id']}")


def _limit_text(s, n=300):
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


@mcp.tool()
def qq_profile(action: str = "get", interests: str = "", blocks: str = "") -> str:
    """查看/设置兴趣画像（供每日精选的 AI 分类使用）。

    Args:
        action: get=查看 / set=设置 / reset=清空
        interests: 兴趣词，逗号分隔（如 "雅思,留学,情感,吃瓜,吐槽"）
        blocks: 过滤词，逗号分隔（如 "出售,代取,偷车"）
    """
    try:
        import profile as prof
        if action == "reset":
            prof.save(interests=[], blocks=[], watch=prof.DEFAULT["watch"])
            return "画像已清空"
        if action == "set":
            interests_list = [x for x in interests.replace("，", ",").split(",") if x.strip()] if interests else None
            blocks_list = [x for x in blocks.replace("，", ",").split(",") if x.strip()] if blocks else None
            d = prof.save(interests=interests_list, blocks=blocks_list)
            return (f"画像已更新\n兴趣: {'、'.join(d['interests']) or '（空）'}\n"
                    f"过滤: {'、'.join(d['blocks']) or '（空）'}\n更新时间: {d['updated_at']}")
        d = prof.load()
        empty = "（空）" if prof.is_empty() else ""
        return (f"兴趣: {'、'.join(d['interests']) or '（空）'}{empty}\n"
                f"过滤: {'、'.join(d['blocks']) or '（空）'}\n"
                f"保留观看: {d.get('watch')}\n"
                f"更新时间: {d.get('updated_at') or '未设置'}")
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_status() -> str:
    """检查 QQ 频道登录状态、默认频道信息与各版块发言权限。"""
    try:
        c = get_client()
        info = c.get_channels()
        perms = [ch for ch in info["channels"] if ch.get("my_speak_permission") == 1]
        try:
            import profile as prof
            prof_state = "未设置（建议先 qq_profile set 建立兴趣画像）" if prof.is_empty() else "已设置"
        except Exception:
            prof_state = "未知"
        lines = [
            f"登录态: {'已登录' if c.is_login else '游客（只读）'}",
            f"频道: {info.get('guild_name')} ({info.get('guild_id')})",
            f"成员数: {info.get('member_num')}",
            f"版块数: {len(info['channels'])}（可发言 {len(perms)} 个）",
            f"兴趣画像: {prof_state}",
            f"配置文件: {CONFIG_PATH}",
        ]
        return "\n".join(lines)
    except QQChannelError as e:
        return f"错误: {e}"
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_channels() -> str:
    """列出频道下所有版块（含 channel_id、名称、我的发言权限）。"""
    try:
        c = get_client()
        info = c.get_channels()
        lines = [f"# {info.get('guild_name')} · {info.get('member_num')} 成员", ""]
        for ch in info["channels"]:
            speak = "可发言" if ch.get("my_speak_permission") == 1 else "禁发"
            lines.append(f"- {ch['name']}  id={ch['channel_id']}  type={ch['type']}  {speak}")
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {e}"


@mcp.tool()
def qq_feeds(days: float = 1, limit: int = 50, channel_id: str = "", sort: str = "time") -> str:
    """拉取频道帖子。

    Args:
        days: 回溯天数（0.5=12小时，3=三天）
        limit: 最多返回条数
        channel_id: 版块ID，留空=帖子广场(635029104)
        sort: time=按发布时间（默认，可回溯任意日期） / hot=推荐流
    """
    try:
        c = get_client()
        since = time.time() - days * 86400 if days > 0 else None
        if sort == "hot":
            feeds = c.get_square_feeds(since_ts=since, limit=limit)
        else:
            cid = channel_id or "635029104"
            feeds = c.get_timeline_feeds(cid, since_ts=since, limit=limit)
        if not feeds:
            return "没有拉到帖子（可能超出可回溯范围或版块为空）"
        lines = [f"{len(feeds)} 条 · {fmt_short(feeds[-1]['create_time'])} ~ {fmt_short(feeds[0]['create_time'])}", ""]
        for f in feeds:
            lines.append(_feed_line(f))
            lines.append(f"  {_limit_text(f['text'], 150)}")
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_sync(days: float = 2, max_pages: int = 300) -> str:
    """把频道帖子同步到本地缓存（增量）。之后用 qq_user_feeds / qq_search 查本地库，不再请求服务器。

    Args:
        days: 同步最近多少天
        max_pages: 最多翻多少页（每页约10条，300页≈3000条≈1-2分钟）
    """
    try:
        c = get_client()
        since = time.time() - days * 86400
        feeds = c.get_timeline_feeds("635029104", since_ts=since, limit=max_pages * 10, max_pages=max_pages)
        n = cache.upsert_feeds(feeds)
        st = cache.stats()
        return (f"同步完成：拉到 {len(feeds)} 条，写入 {n} 条\n"
                f"本地库：{st['total']} 条 / {st['users']} 个用户 / "
                f"{fmt_time(st['oldest'] or 0)} ~ {fmt_time(st['newest'] or 0)}")
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_user_feeds(keyword: str, days: float = 0, limit: int = 30) -> str:
    """按昵称或用户ID查某人发的帖子（查本地缓存，毫秒级）。

    需要先运行 qq_sync 同步数据。

    Args:
        keyword: 昵称关键字或用户ID（如 "昵称" 或用户ID）
        days: 只看最近N天，0=不限
        limit: 最多返回条数
    """
    try:
        rows, total = cache.query(author=keyword, days=days if days > 0 else None, limit=limit)
        if not rows:
            return (f"本地库没有「{keyword}」的帖子（库内共 {total} 条）。\n"
                    f"如果还没同步过，先运行 qq_sync(days=3)。")
        lines = [f"「{keyword}」{len(rows)} 条（本地库 {total} 条）", ""]
        for r in rows:
            lines.append(_feed_line(r))
            lines.append(f"  {_limit_text(r['text'], 150)}")
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_search(keyword: str, days: float = 0, limit: int = 30, order: str = "time") -> str:
    """在本地缓存的帖子里全文搜索（毫秒级）。

    Args:
        keyword: 搜索词
        days: 只看最近N天，0=不限
        limit: 最多返回条数
        order: time=按时间 / hot=按热度
    """
    try:
        rows, total = cache.query(keyword=keyword, days=days if days > 0 else None, limit=limit, order=order)
        if not rows:
            return f"本地库没有包含「{keyword}」的帖子（库内共 {total} 条）。先运行 qq_sync 同步。"
        lines = [f"包含「{keyword}」{len(rows)} 条（本地库 {total} 条）", ""]
        for r in rows:
            lines.append(_feed_line(r))
            lines.append(f"  {_limit_text(r['text'], 150)}")
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_digest(days: float = 1, limit: int = 40, min_likes: int = 5, exclude_trade: bool = True) -> str:
    """生成"精选候选"：从本地库按互动热度粗筛，供 AI 再精筛。

    粗筛规则（零 AI 成本，写在 SQL 里）：
    - 热度分 = 点赞 + 评论×2（评论比点赞更能说明有讨论）
    - 点赞 >= min_likes
    - exclude_trade: 排除纯交易帖（出一/收一/代取/出闲置等）
    - 去重：同一作者同一开头只保留一条

    之后由 AI 在会话里按"有意思"标准精筛（观点/故事/争议/信息增量）。

    Args:
        days: 统计最近多少天
        limit: 最多返回候选数
        min_likes: 最低点赞阈值
        exclude_trade: 是否排除交易类帖子
    """
    try:
        rows, total = cache.query(days=days, limit=5000)
        if not rows:
            return f"本地库没有最近 {days} 天的数据（库内 {total} 条）。先运行 qq_sync。"

        trade_markers = ["出一", "收一", "代取", "出闲置", "收个", "出个", "求购", "拼单", "收个", "出售"]
        seen = set()
        cand = []
        for r in rows:
            text = (r["text"] or "").strip()
            if not text:
                continue
            if r["likes"] < min_likes and r["comments"] < 3:
                continue
            if exclude_trade and any(m in text for m in trade_markers):
                continue
            # 去重：作者 + 前 20 字
            key = (r["author_id"], text[:20])
            if key in seen:
                continue
            seen.add(key)
            score = r["likes"] + (r["comments"] or 0) * 2
            cand.append((score, r))

        cand.sort(key=lambda x: -x[0])
        cand = cand[:limit]
        if not cand:
            return f"最近 {days} 天没有达到阈值（赞≥{min_likes}）的候选，共 {len(rows)} 条。"

        lines = [f"候选 {len(cand)} 条（源 {len(rows)} 条 / 库 {total} 条）", "按热度分排序，等 AI 精筛", ""]
        for i, (score, r) in enumerate(cand, 1):
            lines.append(f"{i}. [{fmt_short(r['create_time'])}] {r['author_nick']} · {r['channel']} · "
                         f"👍{r['likes']}💬{r['comments']} · 分{score} · {r['feed_id']}")
            lines.append(f"   {_limit_text(r['text'], 120)}")
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_comments(feed_id: str, limit: int = 50) -> str:
    """读取某条帖子的评论（含回复、作者、IP 归属地）。"""
    try:
        c = get_client()
        r = c.get_feed_comments(feed_id, limit=limit)
        comments = r.get("comments") or []
        lines = [f"共 {r.get('total')} 条评论，返回 {len(comments)} 条", ""]
        for cm in comments:
            a = cm["author"]
            lines.append(f"[{fmt_time(cm['create_time'])}] {a['nick']}(lv{a.get('level') or '?'}) 👍{cm['likes']} 回复{cm['reply_count']}")
            lines.append(f"  {_limit_text(cm['text'], 200)}")
            for rep in (cm.get("replies") or [])[:3]:
                lines.append(f"    ↳ {rep['author']['nick']}: {_limit_text(rep['text'], 100)}")
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_feed_detail(feed_id: str, author_id: str = "", create_time: int = 0, channel_id: str = "") -> str:
    """获取单条帖子的详情。

    Args:
        feed_id: 帖子ID（形如 B_xxx）
        author_id: 作者ID（qq_feeds 输出里的 author_id）
        create_time: 发帖时间戳（qq_feeds 输出里的 ts）
        channel_id: 版块ID（qq_feeds 输出里的 channel_id）
    """
    try:
        c = get_client()
        # 参数缺省时从本地缓存补全，调用方只需要 feed_id
        if not author_id or not create_time or not channel_id:
            row = cache.get_feed(feed_id)
            if row:
                author_id = author_id or row.get("author_id") or ""
                create_time = create_time or int(row.get("create_time") or 0)
                channel_id = channel_id or row.get("channel_id") or ""
        f = c.get_feed_detail(feed_id, channel_id=channel_id, poster_id=author_id,
                              create_time=create_time or "")
        if not f:
            return "未找到帖子"
        a = f["author"]
        extra = []
        lu = f.get("like_users") or []
        if lu:
            names = [u["nick"] or "?" for u in lu[:5]]
            extra.append("点赞: " + ", ".join(names) + (f" 等{len(lu)}人" if len(lu) > 5 else ""))
        rs = sorted((f.get("reactions") or []), key=lambda x: -x["count"])[:3]
        if rs:
            more = len(f.get("reactions") or []) - len(rs)
            extra.append("表情: " + ", ".join(f"#{r['emoji_id']}×{r['count']}" for r in rs) + (f" 等{more}种" if more > 0 else ""))
        return "\n".join([
            f"作者: {a['nick']} (id={a['id']}, lv{a.get('level')}, {a.get('role') or '普通'})",
            f"时间: {fmt_time(f['create_time'])}  版块: {f['channel']}",
            f"数据: 👍{f['likes']}" + ("(已赞)" if f.get("is_liked") else "") +
            f" 💬{f['comments']} 🔁{f['shares']} ⭐{f.get('collects', 0)}"
            + ("(已收藏)" if f.get("is_collected") else "") +
            f"  IP: {f.get('ip') or '-'}",
            *extra,
            f"feed_id: {f['feed_id']}",
            "",
            f["text"],
        ])
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_stats(days: float = 1, limit: int = 5000, top: int = 15) -> str:
    """按用户统计近期发帖与互动数据（查本地缓存，需先 qq_sync）。

    Args:
        days: 统计最近多少天
        limit: 最多统计多少条帖子
        top: 每榜返回前几名
    """
    try:
        rows, total = cache.query(days=days if days > 0 else None, limit=limit)
        if not rows:
            return f"本地库没有最近 {days} 天的数据（库内共 {total} 条）。先运行 qq_sync。"
        users = {}
        chans = {}
        for f in rows:
            uid = f["author_id"] or f["author_nick"]
            u = users.setdefault(uid, {"nick": f["author_nick"], "posts": 0, "likes": 0, "cmts": 0,
                                       "level": f["level"], "role": f["role"]})
            u["posts"] += 1
            u["likes"] += f["likes"] or 0
            u["cmts"] += f["comments"] or 0
            chans[f["channel"]] = chans.get(f["channel"], 0) + 1
        by_posts = sorted(users.values(), key=lambda x: (-x["posts"], -x["likes"]))[:top]
        by_like = sorted(users.values(), key=lambda x: -x["likes"])[:top]
        lines = [f"样本 {len(rows)} 条帖子 / {len(users)} 个用户（本地库共 {total} 条）", "", "## 发帖最多"]
        for u in by_posts:
            lines.append(f"- {u['nick']} lv{u['level']} {('['+u['role']+']') if u['role'] else ''} 发帖{u['posts']} 赞{u['likes']} 评论{u['cmts']}")
        lines += ["", "## 获赞最多"]
        for u in by_like:
            lines.append(f"- {u['nick']} lv{u['level']} 赞{u['likes']} 发帖{u['posts']} 评论{u['cmts']}")
        lines += ["", "## 版块分布"]
        for k, v in sorted(chans.items(), key=lambda x: -x[1]):
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


@mcp.tool()
def qq_like(feed_id: str, cancel: bool = False) -> str:
    """给帖子点赞或取消点赞（该接口无需图灵签名，可直接调用）。"""
    try:
        c = get_client()
        r = c.like(feed_id, action=0 if cancel else 1)
        return f"{'已取消点赞' if cancel else '已点赞'} feed={feed_id} 当前赞数={r.get('prefer_count') if r else '?'}"
    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
