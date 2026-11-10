"""
QQ频道 Web API 客户端
- 支持登录态(auth) / 游客只读(noauth) 自动切换
- 所有接口均为 pd.qq.com 的 JSON over HTTPS
"""
import json
import time
import gzip
import ssl
import base64
import urllib.request
import urllib.error

BASE = "https://pd.qq.com/qunng/guild/gotrpc"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0")
APP_ID = "537246381"

# 各接口的 service_type：登录态用 auth_value，游客态用 auth_value + 1
SERVICE_TYPES = {
    "channel_list": 1,
    "timeline_feeds": 10,
    "feed_comments": 6,
    "feed_detail": 5,
    "square_feeds": 11,
}


class QQChannelError(Exception):
    pass


def bkn(skey: str) -> int:
    h = 5381
    for c in skey:
        h = (h * 33 + ord(c)) & 0x7FFFFFFF
    return h


def _b64decode(s):
    if not s:
        return ""
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", "ignore")
    except Exception:
        return s


class QQChannelClient:
    def __init__(self, cookie: str = "", guild_id: str = "", guild_number: str = ""):
        self.cookie = cookie.strip()
        self.guild_id = guild_id
        self.guild_number = guild_number
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self._p_skey = self._extract("p_skey")
        self._uuid = self._extract("uuid")

    def _extract(self, name):
        for part in self.cookie.split(";"):
            kv = part.strip().split("=", 1)
            if len(kv) == 2 and kv[0].strip() == name:
                return kv[1].strip()
        return ""

    @property
    def is_login(self):
        return bool(self._p_skey)

    def _cookies(self, auth: bool):
        if auth:
            return self.cookie
        if not self._uuid:
            return ""
        return f"uuid={self._uuid}; p_uin={self._uuid}"

    def call(self, path: str, body: dict, service_type: int, auth: bool = True) -> dict:
        mode = "auth" if auth else "noauth"
        url = f"{BASE}/{mode}/{path}"
        if auth:
            if not self._p_skey:
                raise QQChannelError("无登录态 p_skey，无法调用 auth 接口")
            sep = "&" if "?" in url else "?"
            url += f"{sep}bkn={bkn(self._p_skey)}"
        headers = {
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://pd.qq.com",
            "Referer": f"https://pd.qq.com/g/{self.guild_id}" if self.guild_id else "https://pd.qq.com",
            "x-qq-client-appid": APP_ID,
            "x-oidb": json.dumps({"uint32_service_type": service_type}, separators=(",", ":")),
            "Cookie": self._cookies(auth),
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=25, context=self.ctx) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            if e.code == 501:
                raise QQChannelError("请求被腾讯 WAF 拦截（参数异常或频率过高）")
            raise QQChannelError(f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'ignore')}")
        except Exception as e:
            raise QQChannelError(f"请求失败: {type(e).__name__}: {e}")

        retcode = data.get("retcode")
        if retcode not in (0, None):
            msg = data.get("message") or data.get("tipMsg") or ""
            if retcode == 10006:
                raise QQChannelError(f"登录态失效（{msg}），请更新 cookie")
            raise QQChannelError(f"接口错误 retcode={retcode}: {msg}")
        return data

    # ---------- 读 ----------

    def get_channels(self, guild_id=None, auth=True):
        gid = guild_id or self.guild_id
        st = SERVICE_TYPES["channel_list"] if auth else SERVICE_TYPES["channel_list"] + 1
        body = {
            "polling_guild_id": [gid],
            "cmd0xf5d_req": {
                "rpt_uint64_guild_id": [gid],
                "msg_field_filter": {
                    "uint32_category_info": 1, "uint32_my_speak_permission_type": 1,
                    "uint32_is_channel_admin": 1, "uint32_show_private_channel": 1,
                    "uint32_my_read_seq": 1,
                },
                "channel_info_filter": {
                    "uint32_is_need_name": 1, "uint32_is_need_channel_type": 1,
                    "uint32_is_need_speak_permission": 1, "uint32_start_slow_mode": 1,
                    "uint32_slow_mode_key": 1, "uint32_need_show": 1,
                },
            },
            "cmd0xf57_req": {
                "msg_field_filter": {
                    "msg_guild_info_filter": {
                        "uint32_member_num": 1, "uint32_guild_name": 1, "uint32_guild_status": 1,
                        "uint32_shutup_expire_time": 1, "uint32_guild_number": 1, "uint64_guild_id": 1,
                        "uint32_is_visible_for_visitor": 1, "uint32_speak_threshold": 1,
                        "uint32_vistor_face_distinguish": 1, "uint32_vistor_interaction": 1,
                        "uint32_owner_tinyid": 1, "uint32_guild_type": 1,
                    },
                    "msg_cmd_uin_info_filter": {
                        "uint32_join_time": 1, "uint32_role": 1, "uint32_tinyid": 1,
                        "uint32_shutup_expire_time": 1, "uint32_is_banned": 1,
                    },
                },
                "rpt_req_guild_info_list": [{"uint64_guild_id": gid}],
            },
        }
        j = self.call("trpc.group_pro.cmd0x907e.Cmd0x907e/HandleProcess?channelList&polling&isActiveGuild=1", body, st, auth)
        d = j.get("data") or {}
        out = {"guild_id": gid, "guild_name": "", "member_num": 0, "channels": []}
        gi = (d.get("cmd0xf57_rsp") or {}).get("rpt_rsp_guild_info_list") or []
        if gi:
            mg = gi[0].get("msg_guild_info") or {}
            out["guild_name"] = _b64decode(mg.get("bytes_guild_name"))
            out["member_num"] = mg.get("uint32_member_num")
            out["guild_number"] = _b64decode(mg.get("bytes_guild_number"))
        cl = (d.get("cmd0xf5d_rsp") or {}).get("rpt_msg_guild_info_list") or []
        for g in cl:
            for c in (g.get("rpt_msg_channel_list") or []):
                out["channels"].append({
                    "channel_id": c.get("uint64_channel_id"),
                    "name": _b64decode(c.get("bytes_channel_name")),
                    "type": c.get("uint32_channel_type"),
                    "speak_permission": c.get("uint32_speak_permission"),
                    "my_speak_permission": c.get("uint32_my_speak_permission_type"),
                })
        return out

    def get_timeline_feeds(self, channel_id, guild_id=None, since_ts=None, limit=200, max_pages=80):
        gid = guild_id or self.guild_id
        auth = self.is_login
        st = SERVICE_TYPES["timeline_feeds"] if auth else SERVICE_TYPES["timeline_feeds"] + 1
        cursor = ""
        out = []
        pages = 0
        while len(out) < limit and pages < max_pages:
            body = {
                "count": 10, "from": 7,
                "channelSign": {"guild_id": gid, "channel_id": channel_id},
                "feedAttchInfo": cursor,
                "sortOption": 1,  # 按发布时间
                "need_top_info": False,
            }
            j = self.call("trpc.qchannel.commreader.ComReader/GetChannelTimelineFeeds", body, st, auth)
            d = j.get("data") or {}
            feeds = d.get("vecFeed") or []
            if not feeds:
                break
            stop = False
            for f in feeds:
                cts = int(f.get("createTime") or 0)
                if since_ts and cts < since_ts:
                    stop = True
                    break
                out.append(normalize_feed(f))
                if len(out) >= limit:
                    stop = True
                    break
            pages += 1
            if stop:
                break
            nxt = d.get("feedAttchInfo") or ""
            if not nxt or nxt == cursor:
                break
            cursor = nxt
            time.sleep(0.25)
        return out

    def get_square_feeds(self, guild_id=None, since_ts=None, limit=100, max_pages=60):
        """帖子广场/热门流（GetGuildFeeds，推荐排序）"""
        gid = guild_id or self.guild_id
        auth = self.is_login
        st = SERVICE_TYPES["square_feeds"]
        cursor = ""
        out = []
        pages = 0
        while len(out) < limit and pages < max_pages:
            body = {"count": 10, "from": 0, "guild_id": gid, "get_type": 1,
                    "feedAttchInfo": cursor, "sortOption": 0,
                    "need_channel_list": False, "need_top_info": False}
            j = self.call("trpc.qchannel.commreader.ComReader/GetGuildFeeds", body, st, auth)
            d = j.get("data") or {}
            feeds = d.get("vecFeed") or []
            if not feeds:
                break
            stop = False
            for f in feeds:
                cts = int(f.get("createTime") or 0)
                if since_ts and cts < since_ts:
                    stop = True
                    break
                out.append(normalize_feed(f))
                if len(out) >= limit:
                    stop = True
                    break
            pages += 1
            if stop:
                break
            nxt = d.get("feedAttchInfo") or ""
            if not nxt or nxt == cursor:
                break
            cursor = nxt
            time.sleep(0.25)
        return out

    def get_user_feeds(self, keyword, days=7.0, limit=3000, max_pages=400):
        """按昵称或用户ID过滤某人的帖子（翻时间线实现）"""
        import time as _t
        since = _t.time() - days * 86400 if days > 0 else None
        feeds = self.get_timeline_feeds("635029104", since_ts=since, limit=limit, max_pages=max_pages)
        kw = (keyword or "").strip()
        if not kw:
            return feeds
        return [f for f in feeds if kw == f["author"].get("id") or kw in (f["author"].get("nick") or "")]

    def get_feed_comments(self, feed_id, limit=50, guild_number=None):
        auth = self.is_login
        st = SERVICE_TYPES["feed_comments"] if auth else SERVICE_TYPES["feed_comments"] + 1
        gnum = guild_number or self.guild_number
        cursor = ""
        out = []
        while len(out) < limit:
            body = {
                "feedId": feed_id, "listNum": 20, "from": 1, "src": 0,
                "attchInfo": cursor, "needInsertCommentID": "", "needInsertReplyID": "",
                "channelSign": {"guild_number": gnum},
                "extInfo": {"mapInfo": [{"key": "qc-tabid", "value": ""}, {"key": "qc-pageid", "value": ""}]},
                "rankingType": 1, "replyListNum": 1,
            }
            j = self.call("trpc.qchannel.commreader.ComReader/GetFeedComments", body, st, auth)
            d = j.get("data") or {}
            comments = d.get("vecComment") or []
            if not comments:
                break
            for c in comments:
                out.append(normalize_comment(c))
                if len(out) >= limit:
                    break
            nxt = d.get("attchInfo") or ""
            if not nxt or nxt == cursor or d.get("isFinish"):
                break
            cursor = nxt
            time.sleep(0.25)
        return {"total": d.get("totalNum"), "comments": out}

    def get_feed_detail(self, feed_id, guild_id=None, channel_id="", poster_id="", create_time="", guild_number=None):
        auth = self.is_login
        st = SERVICE_TYPES["feed_detail"] if auth else SERVICE_TYPES["feed_detail"] + 1
        sign = {"guild_id": guild_id or self.guild_id}
        if channel_id:
            sign["channel_id"] = str(channel_id)
        body = {
            "feedId": feed_id,
            "userId": str(poster_id or ""),
            "createTime": str(create_time or ""),
            "from": 2,
            "detail_type": 1,
            "channelSign": sign,
            "extInfo": {"mapInfo": []},
        }
        j = self.call("trpc.qchannel.commreader.ComReader/GetFeedDetail", body, st, auth)
        d = j.get("data") or {}
        f = d.get("feed") or {}
        return normalize_feed(f) if f else {}

    # ---------- 写（需图灵签名，仅支持点赞） ----------

    def like(self, feed_id, action=1):
        """action: 1=点赞, 0=取消。该接口不需要图灵签名"""
        if not self.is_login:
            raise QQChannelError("点赞需要登录态")
        body = {"feed_id": feed_id, "action": action,
                "extInfo": {"mapInfo": [{"key": "page_id", "value": "pg_sgrp_forum_detail"}]}}
        j = self.call("trpc.qchannel.commwriter.ComWriter/DoFeedPrefer5", body, 3, True)
        return j.get("data")


def _text_of(obj):
    """从 title/contents 结构中提取纯文本"""
    parts = []
    for c in ((obj or {}).get("contents") or []):
        t = (c.get("text_content") or {}).get("text")
        if t:
            parts.append(t)
    return "".join(parts).strip()


def _full_text(f):
    """取完整正文：title / contents / content_with_style 里最长的一份

    title 往往只是标题（一句话），正文在 content_with_style.paragraphs，
    必须取最长者，否则长帖会被截成标题。
    """
    candidates = [
        _text_of(f.get("title")),
        _text_of(f.get("contents")),
    ]
    cws = f.get("content_with_style") or {}
    lines = []
    for p in (cws.get("paragraphs") or []):
        line = ""
        for e in (p.get("elems") or []):
            t = ((e.get("text") or {}).get("text_content") or {}).get("text")
            if t:
                line += t
        if line.strip():
            lines.append(line)
    if lines:
        candidates.append("\n".join(lines))
    return max(candidates, key=len).strip()


def normalize_feed(f):
    p = f.get("poster") or {}
    ci = f.get("channelInfo") or {}
    sign = ci.get("sign") or {}
    level = (p.get("guild_user_level") or {}).get("level")
    role = (p.get("manage_tag") or {}).get("tag_name")
    images = []
    for im in (f.get("images") or []):
        u = im.get("pic_url") or im.get("url")
        if u:
            images.append(u)
    return {
        "feed_id": (f.get("emotionReaction") or {}).get("id") or f.get("feed_id") or "",
        "text": _full_text(f),
        "author": {"id": p.get("id"), "nick": p.get("nick"), "level": level, "role": role},
        "create_time": int(f.get("createTime") or 0),
        "channel": ci.get("name") or "",
        "channel_id": sign.get("channel_id") or "",
        "guild_id": sign.get("guild_id") or "",
        "likes": ((f.get("total_prefer") or {}).get("prefer_count")
                  or (f.get("total_like") or {}).get("like_count") or 0),
        "is_liked": bool((f.get("total_like") or {}).get("is_clicked")
                         or (f.get("total_prefer") or {}).get("prefer_status") == 1),
        "comments": f.get("commentCount") or 0,
        "shares": (f.get("share") or {}).get("sharedCount") or 0,
        "collects": (f.get("total_collect") or {}).get("collect_count") or 0,
        "is_collected": bool((f.get("total_collect") or {}).get("is_collected")),
        "like_users": [
            {"nick": u.get("nick"), "id": u.get("id")}
            for u in (f.get("external_like_user_list") or [])
        ],
        "reactions": [
            {"emoji_id": r.get("emoji_id"), "count": int(r.get("cnt") or 0)}
            for r in ((f.get("emotionReaction") or {}).get("emoji_reaction_list") or [])
            if r.get("cnt")
        ],
        "views": f.get("view_count") or f.get("views") or None,
        "images": images,
        "ip": f.get("ip_location_province") or "",
    }


def normalize_comment(c):
    p = c.get("postUser") or {}
    rc = c.get("richContents") or {}
    txt = _text_of(rc)
    replies = []
    for r in (c.get("vecReply") or []):
        rp = r.get("postUser") or {}
        replies.append({
            "id": r.get("id"),
            "author": {"id": rp.get("id"), "nick": rp.get("nick")},
            "text": _text_of(r.get("richContents")),
            "create_time": int(r.get("createTime") or 0),
        })
    return {
        "id": c.get("id"),
        "author": {"id": p.get("id"), "nick": p.get("nick"),
                   "level": (p.get("guild_user_level") or {}).get("level"),
                   "role": (p.get("manage_tag") or {}).get("tag_name")},
        "text": txt,
        "create_time": int(c.get("createTime") or 0),
        "likes": ((c.get("likeInfo") or {}).get("count") or 0),
        "reply_count": c.get("replyCount") or 0,
        "replies": replies,
        "ip": rc.get("ip_location_province") or "",
    }
