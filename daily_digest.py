"""
每日精选：增量分类新帖，生成每日 digest

- 只判断没分类过的帖子（classified 表去重）
- 分类结果写回 classified，下次不再重复判断
- 生成 Markdown 到 Daily_usage/QQ频道精选/YYYY-MM-DD.md
"""
import os
import sys
import json
import time
import ssl
import urllib.request
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import cache  # noqa: E402
import profile  # noqa: E402

KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("LLM_API_KEY")
URL = "https://api.deepseek.com/v1/chat/completions"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
OUT_DIR = r"e:\Pycharm_Projects\Daily_usage\QQ频道MCP\精选"
LOG = os.path.join(BASE, "digest.log")
MODEL = "deepseek-chat"


def build_system():
    p = profile.load()
    interests = "、".join(p["interests"]) if p["interests"] else "（尚未设置，按通用兴趣判断）"
    blocks = "、".join(p["blocks"]) if p["blocks"] else "（尚未设置）"
    return f"""你是我的频道信息筛选助手。按我的兴趣对帖子分类。

【不感兴趣 / 直接忽略】
- 固定排除：出售、收购、代取、拼单、求购、出闲置、回收、偷车、拔电源、外卖被偷、挂人、抱怨琐事
- 我的过滤词：{blocks}

【感兴趣 / interesting】
- 我的兴趣：{interests}
- 有故事、有观点、有信息增量的校园内容

【保留观看 / watch】
- {p.get('watch') or '热度高但信息量低'}

输出严格 JSON，不要解释，不要输出 ignore 条目：
{{"interesting":[{{"id":"...","reason":"10字内"}}],"watch":[{{"id":"..."}}]}}
只输出你判断为 interesting 和 watch 的条目。
**最多输出 30 条 interesting、20 条 watch，优先挑最值得看的。**"""


SYSTEM = build_system()


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        open(LOG, "a", encoding="utf-8").write(line + "\n")
    except Exception:
        pass


def call_ai(prompt):
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": build_system()}, {"role": "user", "content": prompt}],
            "temperature": 0.2, "max_tokens": 8000}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                                 method="POST")
    t = time.time()
    r = urllib.request.urlopen(req, timeout=300, context=CTX)
    j = json.loads(r.read().decode("utf-8", "ignore"))
    return j, time.time() - t


def build_prompt(rows):
    lines = []
    for r in rows:
        text = (r["text"] or "").replace("\n", " ")[:180]
        lines.append(f'id={r["feed_id"]} | {r["author_nick"]} | 赞{r["likes"]} 评{r["comments"]} | {text}')
    return "\n".join(lines)


def classify_new(limit=3000, batch_size=700):
    rows = cache.unclassified(limit)
    if not rows:
        log("没有待分类的新帖")
        return 0
    log(f"待分类 {len(rows)} 条，分 {(len(rows)+batch_size-1)//batch_size} 批...")
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        total += classify_batch(batch)
        time.sleep(1)
    return total


def classify_batch(rows):
    prompt = build_prompt(rows)
    try:
        j, dt = call_ai(prompt)
    except Exception as e:
        log(f"AI 调用失败: {type(e).__name__}: {e}")
        return 0
    ch = j["choices"][0]
    content = ch["message"]["content"]
    try:
        data = json.loads(content)
    except Exception:
        log(f"JSON 解析失败（finish={ch.get('finish_reason')}）: {content[:150]}")
        return 0

    interesting = data.get("interesting", [])
    watch = data.get("watch", [])
    hit = {x.get("id") for x in interesting} | {x.get("id") for x in watch}
    reason_map = {x.get("id"): x.get("reason", "") for x in interesting}

    items = []
    for r in rows:
        fid = r["feed_id"]
        if fid in hit:
            cat = "interesting" if fid in reason_map else "watch"
            items.append((fid, cat, reason_map.get(fid, "")))
        else:
            items.append((fid, "ignore", ""))
    n = cache.save_classifications(items, MODEL)
    u = j.get("usage", {})
    log(f"批次 {len(rows)} 条 -> 分类 {n}（interesting {len(interesting)} / watch {len(watch)}）"
        f" 耗时 {dt:.1f}s in {u.get('prompt_tokens')} out {u.get('completion_tokens')}")
    return n


def write_digest():
    con = cache.connect()
    today0 = int(datetime.combine(date.today(), datetime.min.time()).timestamp())
    rows = con.execute("""
        SELECT f.*, c.category, c.reason FROM feeds f
        JOIN classified c ON f.feed_id = c.feed_id
        WHERE c.category IN ('interesting','watch') AND f.create_time >= ?
        ORDER BY c.category, f.create_time DESC
    """, (today0,)).fetchall()
    con.close()
    if not rows:
        log("今天没有精选")
        return None
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{date.today():%Y-%m-%d}.md")
    inter = [r for r in rows if r["category"] == "interesting"]
    watch = [r for r in rows if r["category"] == "watch"]
    lines = [f"# QQ频道精选 · {date.today():%Y-%m-%d}", ""]
    lines.append(f"> 今日 {len(inter)} 条感兴趣，{len(watch)} 条保留观看")
    lines.append("")
    lines.append("## 感兴趣")
    lines.append("")
    for i, r in enumerate(inter, 1):
        t = datetime.fromtimestamp(r["create_time"]).strftime("%H:%M")
        lines.append(f"### {i}. {r['reason'] or r['text'][:20]}")
        lines.append(f"`{t}` · {r['author_nick']} · {r['channel']} · 👍{r['likes']}💬{r['comments']}")
        lines.append("")
        lines.append(f"{r['text'][:200]}")
        lines.append("")
        lines.append(f"<sub>feed_id: {r['feed_id']}</sub>")
        lines.append("")
    if watch:
        lines.append("## 保留观看")
        lines.append("")
        for r in watch:
            t = datetime.fromtimestamp(r["create_time"]).strftime("%H:%M")
            lines.append(f"- `{t}` {r['author_nick']} · 👍{r['likes']}💬{r['comments']} · {r['text'][:60]}")
        lines.append("")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    log(f"精选已生成: {path}")
    return path


def main():
    n = classify_new()
    if n:
        write_digest()
    else:
        # 即使没有新分类，也尝试刷新当天 digest
        write_digest()


if __name__ == "__main__":
    main()
