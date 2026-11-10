"""用户画像：兴趣词 / 过滤词，供 AI 分类使用"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(BASE, "profile.json")

DEFAULT = {
    "interests": [],
    "blocks": [],
    "watch": "热度高但信息量低，可以不参与但想看一眼",
    "updated_at": "",
}


def load():
    if not os.path.exists(PATH):
        return dict(DEFAULT)
    try:
        d = json.load(open(PATH, encoding="utf-8"))
        for k, v in DEFAULT.items():
            d.setdefault(k, v)
        return d
    except Exception:
        return dict(DEFAULT)


def save(interests=None, blocks=None, watch=None):
    d = load()
    if interests is not None:
        d["interests"] = [x.strip() for x in interests if x.strip()]
    if blocks is not None:
        d["blocks"] = [x.strip() for x in blocks if x.strip()]
    if watch is not None:
        d["watch"] = watch
    d["updated_at"] = datetime.now().isoformat(timespec="seconds")
    json.dump(d, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return d


def is_empty():
    d = load()
    return not d["interests"] and not d["blocks"]
