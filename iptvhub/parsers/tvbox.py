# -*- coding: utf-8 -*-
"""TVBox JSON 解析。

实测结构（gaotianliuyun/gao 的 0821.json）：
    {
      "spider": "...",
      "lives": [
        {"name":"初秋语•ipv4", "type":0, "url":"./list.txt",
         "playerType":2, "epg":"http://epg.112114.xyz/?ch={name}&date={date}"},
        {"name":"YanG•综合", "type":0, "url":"https://tv.iill.top/m3u/Gather"}
      ],
      "sites":[...], "parses":[...]
    }

要点：
  1. lives 里的 url 可能是**相对路径**（./list.txt），需按订阅地址的 base 展开；
  2. type=0/1 表示远程列表，需二次拉取（deferred）；
  3. 多仓结构（顶层 urls 数组）也要支持。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse as up

import aiohttp

from ..config import CONFIG
from .base import Channel

log = logging.getLogger("tvbox")

DEFERRED_PREFIX = "__DEFERRED__"

# 远程列表型 live 的 type 取值
REMOTE_TYPES = {"0", "1"}


def _absolutize(url: str, base: str) -> str:
    """
    把相对路径展开为绝对 URL。

    @param url   可能是 ./list.txt 或 https://... 的地址
    @param base  该 JSON 自身的地址
    @retval       绝对地址
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "rtmp://", "rtsp://",
                       "udp://", "rtp://", "igmp://")):
        return url
    if not base:
        return url
    return up.urljoin(base, url)


def parse_lives(text: str, source: str = "", weight: float = 1.0,
                base_url: str = "") -> list[Channel]:
    """
    解析 TVBox JSON 的 lives 字段。

    type=0/1 的条目标记为 DEFERRED，交由 resolve_deferred 二次拉取；
    相对路径按 base_url 展开为绝对地址。

    @param text      JSON 正文
    @param source    来源上游名
    @param weight    来源权重
    @param base_url  该 JSON 自身的地址，用于展开相对路径
    @retval          Channel 列表（含 DEFERRED 占位）
    """
    out: list[Channel] = []
    try:
        data = json.loads(text)
    except Exception as exc:
        log.warning("tvbox json 解析失败: %s", exc)
        return out

    lives = data.get("lives") or []
    log.info("lives 条目 %d 个", len(lives))

    # 源级黑名单：整体跳过音乐/点播站。
    # 实测 16万•MV 会不断更换 CDN 域名（bdstatic.com -> mvbox.cn ->
    # haiqu.vip -> 68tool.com -> yximgs.com），追域名是打地鼠，
    # 必须在源级别禁掉。
    from ..config import SUB_FEED_BLACKLIST

    skipped = 0
    for item in lives:
        raw_url = (item.get("url") or "").strip()
        if not raw_url:
            continue

        gname = item.get("name") or "TVBox"

        if any(bl in gname for bl in SUB_FEED_BLACKLIST):
            skipped += 1
            log.info("跳过源级黑名单: %s", gname)
            continue

        url = _absolutize(raw_url, base_url)
        ltype = str(item.get("type", "0"))
        epg = (item.get("epg") or "").strip()

        is_remote = (ltype in REMOTE_TYPES
                     or url.endswith((".m3u", ".m3u8", ".txt"))
                     or "/m3u/" in url)

        if is_remote:
            c = Channel(name=DEFERRED_PREFIX + gname, url=url,
                        group=gname, source=source, weight=weight)
            c.tvg_logo = epg          # 暂存 epg，展开时可用于回填
            out.append(c)
        else:
            out.append(Channel(name=gname, url=url, group=gname,
                               source=source, weight=weight))

    if skipped:
        log.info("按源级黑名单跳过 %d 个二级订阅", skipped)

    return out


def parse_multi(text: str) -> list[dict]:
    """
    解析多仓 JSON 的 urls 数组（部分仓库用这种结构做聚合入口）。

    @param text  多仓 JSON 正文
    @retval      [{"name": ..., "url": ...}]
    """
    try:
        data = json.loads(text)
    except Exception:
        return []

    res = []
    for it in (data.get("urls") or []):
        u = (it.get("url") or "").strip()
        if u.startswith("http"):
            res.append({"name": it.get("name") or u[:32], "url": u})
    return res


async def _fetch_sub(session: aiohttp.ClientSession, url: str) -> str:
    """
    拉取二级订阅内容，带镜像回退与 IDN 转码。

    二级源里大量出现 raw.githubusercontent.com 直链（国内不通）以及
    中文域名（需 IDN 转码），这里统一走 fetcher 的候选链逻辑。

    @param session  aiohttp 会话
    @param url      订阅地址
    @retval         正文，失败返回空串
    """
    if not url:
        return ""

    from ..fetcher import mirror_candidates

    for cand in mirror_candidates(url):
        try:
            async with session.get(
                    cand, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    log.debug("二级订阅 HTTP %s: %s", r.status, cand)
                    continue
                text = await r.text(errors="ignore")
                if len(text) < 16:
                    continue
                log.debug("二级订阅 ok %s (%d bytes)", cand, len(text))
                return text
        except Exception as exc:
            log.debug("二级订阅失败 %s: %s", cand, exc)
            continue
    return ""


async def resolve_deferred(channels: list[Channel]) -> list[Channel]:
    """
    并发二次拉取 DEFERRED 条目并解析为真实频道。

    @param channels  含 DEFERRED 的频道列表
    @retval          展开后的真实频道列表
    """
    from .m3u import parse as parse_m3u
    from .plain_txt import parse as parse_txt

    real = [c for c in channels if not c.name.startswith(DEFERRED_PREFIX)]
    todo = [c for c in channels if c.name.startswith(DEFERRED_PREFIX)]
    if not todo:
        return real

    log.info("二级订阅待展开 %d 个", len(todo))

    conn = aiohttp.TCPConnector(limit=16, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers=CONFIG["headers"]) as s:
        texts = await asyncio.gather(*(_fetch_sub(s, c.url) for c in todo))

    ok = 0
    for c, t in zip(todo, texts):
        if not t:
            continue
        gname = c.name.replace(DEFERRED_PREFIX, "")
        subs = parse_m3u(t, c.source, c.weight * 0.9)
        if not subs:
            subs = parse_txt(t, c.source, c.weight * 0.9)
        if subs:
            ok += 1
        for sc in subs:
            sc.group = gname or sc.group
        real.extend(subs)

    log.info("二级订阅展开成功 %d/%d，新增 %d 条",
             ok, len(todo), len(real) - (len(channels) - len(todo)))
    return real
