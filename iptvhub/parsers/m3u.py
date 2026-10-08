# -*- coding: utf-8 -*-
"""m3u / m3u8 播放列表解析器（状态机，容忍脏数据）。"""
from __future__ import annotations

import re

from .base import Channel

ATTR = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')
URL_RE = re.compile(r'^(https?|rtmp|rtsp|rtp|rtp2|udp|igmp)://', re.I)


def parse(text: str, source: str = "", weight: float = 1.0) -> list[Channel]:
    """
    解析 m3u 文本为 Channel 列表。

    @param text    m3u 正文
    @param source  来源上游名
    @param weight  来源权重
    @retval        Channel 列表
    """
    out: list[Channel] = []
    pending: dict | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            attrs = dict(ATTR.findall(line))
            name = line.split(",", 1)[1].strip() if "," in line else ""
            pending = {
                "name": name or attrs.get("tvg-name", ""),
                "group": attrs.get("group-title", "") or "未分组",
                "tvg_id": attrs.get("tvg-id", ""),
                "tvg_logo": attrs.get("tvg-logo", ""),
            }
            continue

        if line.startswith("#"):
            continue

        if URL_RE.match(line):
            if pending and pending["name"]:
                out.append(Channel(
                    name=pending["name"],
                    url=line,
                    group=pending["group"],
                    tvg_id=pending["tvg_id"],
                    tvg_logo=pending["tvg_logo"],
                    source=source,
                    weight=weight,
                ))
            pending = None

    return out
