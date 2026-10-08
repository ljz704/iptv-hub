# -*- coding: utf-8 -*-
"""「频道名,url」纯文本解析，兼容逗号/竖线/制表符分隔与 #genre# 分组头。"""
from __future__ import annotations

import re

from .base import Channel

URL_RE = re.compile(r'(?P<url>(?:https?|rtmp|rtsp|rtp|rtp2|udp|igmp)://[^\s,|]+)', re.I)
GENRE_RE = re.compile(r'^#genre#\s*(.*)$', re.I)
NAME_ID_RE = re.compile(r'^(?P<name>.+?)\s*[（(]?(?P<gid>[a-zA-Z0-9_\-\.]+)\.(?:m3u8|ts)[）)]?$')


def parse(text: str, source: str = "", weight: float = 1.0) -> list[Channel]:
    """
    解析纯文本频道列表。

    支持格式：
        CCTV-1,http://a/b.m3u8
        央视一套|http://a/c.m3u8
        #genre#央视
        CCTV-1,http://a/b.m3u8

    @param text    正文
    @param source  来源上游名
    @param weight  来源权重
    @retval        Channel 列表
    """
    out: list[Channel] = []
    group = "未分组"

    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue

        gm = GENRE_RE.match(line)
        if gm:
            group = gm.group(1).strip() or "未分组"
            continue

        if line.startswith("#"):
            continue

        m = URL_RE.search(line)
        if not m:
            continue

        url = m.group("url").rstrip(",|")
        head = line[:m.start()].strip().strip(",|").strip()
        if not head:
            head = url.rsplit("/", 1)[-1]

        name, gid = head, ""
        nm = NAME_ID_RE.match(head)
        if nm:
            name, gid = nm.group("name").strip(), nm.group("gid")

        out.append(Channel(
            name=name,
            url=url,
            group=group,
            tvg_id=gid,
            source=source,
            weight=weight,
        ))

    return out
