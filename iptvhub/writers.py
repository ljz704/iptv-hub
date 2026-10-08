# -*- coding: utf-8 -*-
"""输出写入：标准 m3u、多源 m3u、纯文本、TVBox JSON。

多源 m3u 用自定义扩展属性承载备用地址，供改造后的播放器读取：
    #EXTINF:-1 tvg-id="CCTV-1" group-title="央视",CCTV-1
    #EXTM3U-FALLBACK:http://备选地址1|http://备选地址2
    http://主地址
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path

from .classify import classify, group_rank
from .config import CONFIG
from .parsers.base import Channel

log = logging.getLogger("writers")
Q = CONFIG["quality"]


def _group_channels(channels: list[Channel]) -> "OrderedDict[str, list[Channel]]":
    """按分组聚合，分组顺序按 GROUP_ORDER 排列。"""
    buckets: dict[str, list[Channel]] = {}
    for c in channels:
        c.group = classify(c.name, c.group)
        buckets.setdefault(c.group, []).append(c)

    ordered: "OrderedDict[str, list[Channel]]" = OrderedDict()
    for g in sorted(buckets.keys(), key=group_rank):
        ordered[g] = buckets[g]
    return ordered


def write_m3u(channels: list[Channel], path: str) -> None:
    """
    输出标准 m3u，同频道多条 url 依次列出（播放器可自行跳过失败的）。

    @param channels  Channel 列表
    @param path      输出路径
    """
    ordered = _group_channels(channels)
    lines = ["#EXTM3U"]

    for group, items in ordered.items():
        for c in items:
            attrs = f'group-title="{group}"'
            if c.tvg_id:
                attrs += f' tvg-id="{c.tvg_id}"'
            if c.tvg_logo:
                attrs += f' tvg-logo="{c.tvg_logo}"'
            attrs += f' tvg-name="{c.name}"'
            lines.append(f"#EXTINF:-1 {attrs},{c.name}")
            lines.append(c.url)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("已写出 %s (%d 条)", path, len(channels))


def write_multi_m3u(channels: list[Channel], path: str) -> None:
    """
    输出「主地址 + 备用地址」结构的 m3u。

    每个频道主地址在 EXTINF 后一行，备用地址写入 #EXTM3U-FALLBACK 扩展行。

    @param channels  Channel 列表（同名多条已按权重排好序）
    @param path      输出路径
    """
    grouped: dict[str, list[Channel]] = {}
    meta: dict[str, Channel] = {}
    for c in channels:
        grouped.setdefault(c.name, []).append(c)
        meta.setdefault(c.name, c)

    lines = ["#EXTM3U"]
    for name, items in grouped.items():
        head = meta[name]
        group = classify(name, head.group)
        attrs = (f'tvg-name="{name}" group-title="{group}"'
                 f' source-count="{len(items)}"')
        if head.tvg_id:
            attrs += f' tvg-id="{head.tvg_id}"'
        if head.tvg_logo:
            attrs += f' tvg-logo="{head.tvg_logo}"'
        lines.append(f"#EXTINF:-1 {attrs},{name}")

        primary, *rest = items
        if rest:
            # 自定义扩展行：管道分隔的备用地址，改造版播放器解析此字段
            lines.append("#EXTM3U-FALLBACK:" + "|".join(r.url for r in rest))
        lines.append(primary.url)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("已写出 %s (%d 个频道，含备用源)", path, len(grouped))


def write_txt(channels: list[Channel], path: str) -> None:
    """
    输出「频道名,url」纯文本，带 #genre# 分组头。

    @param channels  Channel 列表
    @param path      输出路径
    """
    ordered = _group_channels(channels)
    lines = []
    for group, items in ordered.items():
        lines.append(f"#genre#{group}")
        for c in items:
            lines.append(f"{c.name},{c.url}")

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("已写出 %s", path)


def write_tvbox(channels: list[Channel], path: str,
                m3u_ref: str = "./live.m3u") -> None:
    """
    输出 TVBox JSON 配置，供 FongMi/TV 等播放器直接订阅。

    @param channels  Channel 列表
    @param path      输出路径
    @param m3u_ref   引用的 m3u 相对路径
    """
    cfg = {
        "lives": [
            {
                "name": "聚合直播",
                "type": 0,
                "url": m3u_ref,
                "playerType": 1,
                "epg": "",
            }
        ]
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    log.info("已写出 %s", path)


def write_stats(stats: dict, path: str) -> None:
    """写出运行统计 JSON，供告警与趋势分析使用。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    log.info("已写出 %s", path)
