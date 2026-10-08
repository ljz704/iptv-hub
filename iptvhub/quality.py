# -*- coding: utf-8 -*-
"""质量统计与告警：存活率计算、阈值判定、告警输出。"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .config import CONFIG

log = logging.getLogger("quality")
Q = CONFIG["quality"]


def build_stats(total: int, alive: int,
                per_upstream: dict[str, dict]) -> dict:
    """
    汇总本次运行统计。

    @param total        聚合后总条数
    @param alive        存活条数
    @param per_upstream 各上游 {名称: {"raw": n, "alive": m}}
    @retval             统计字典
    """
    ratio = (alive / total) if total else 0.0
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "alive": alive,
        "alive_ratio": round(ratio, 4),
        "per_upstream": per_upstream,
        "threshold": Q.min_alive_ratio,
        "healthy": ratio >= Q.min_alive_ratio,
    }


def check_alerts(stats: dict) -> list[str]:
    """
    按阈值生成告警文本列表。

    @param stats  build_stats 的输出
    @retval       告警消息列表，空表示健康
    """
    alerts = []
    if stats["total"] == 0:
        alerts.append("严重：聚合结果为空，所有上游可能均已失效")
        return alerts

    if not stats["healthy"]:
        alerts.append(
            f"存活率过低：{stats['alive']}/{stats['total']} "
            f"= {stats['alive_ratio']:.1%}，低于阈值 {stats['threshold']:.0%}")

    for name, s in stats.get("per_upstream", {}).items():
        raw = s.get("raw", 0)
        if raw < 20:
            continue
        r = s.get("alive", 0) / raw
        if r < Q.per_upstream_min:
            alerts.append(f"上游 {name} 存活率异常：{s.get('alive', 0)}/{raw} = {r:.1%}")
    return alerts


def notify(messages: list[str]) -> None:
    """
    推送告警：优先 Server 酱，其次 Telegram，均未配置则只打日志。

    依赖环境变量：
        SERVERCHAN_KEY    Server 酱 SendKey
        TG_BOT_TOKEN      Telegram Bot Token
        TG_CHAT_ID        Telegram Chat ID

    @param messages  告警文本列表
    """
    if not messages:
        return
    text = "【IPTV 源告警】\n" + "\n".join(f"· {m}" for m in messages)
    log.warning(text)

    key = os.getenv("SERVERCHAN_KEY")
    if key:
        try:
            url = f"https://sctapi.ftqq.com/{key}.send"
            data = urllib.parse.urlencode({"title": "IPTV 源告警", "desp": text}).encode()
            urllib.request.urlopen(
                urllib.request.Request(url, data=data), timeout=10).read()
            log.info("Server 酱告警已发送")
        except Exception as exc:
            log.error("Server 酱发送失败: %s", exc)

    token, chat = os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID")
    if token and chat:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
            urllib.request.urlopen(
                urllib.request.Request(url, data=data), timeout=10).read()
            log.info("Telegram 告警已发送")
        except Exception as exc:
            log.error("Telegram 发送失败: %s", exc)


def append_history(stats: dict, path: str = "data/history.jsonl") -> None:
    """
    追加一行历史记录，用于存活率趋势分析。

    @param stats  统计字典
    @param path   历史文件路径
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stats, ensure_ascii=False) + "\n")
