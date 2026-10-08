# -*- coding: utf-8 -*-
"""并发健康探测：GET 前 N 字节 -> 流特征判定 -> 延迟评分。

判定顺序：组播/内网直接标记放行，避免误杀；其余走 HTTP 探测。
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time
import urllib.parse as up

import aiohttp

from .config import CONFIG
from .parsers.base import Channel

log = logging.getLogger("probe")
P = CONFIG["probe"]

M3U8_MAGIC = (b"#EXTM3U", b"#EXT-X-")
HTML_HINT = (b"<html", b"<!doctype", b"<head", b"<body", b"404", b"not found")
PARK_HINT = (b"domain for sale", b"parked", b"coming soon",
             b"under construction", b"this domain")
UDP_RE = re.compile(r'^(udp|rtp|rtp2|igmp)://', re.I)

PRIVATE_NETS = [ipaddress.ip_network(c) for c in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
    "100.64.0.0/10", "239.0.0.0/8", "224.0.0.0/4", "169.254.0.0/16",
    "fc00::/7", "fe80::/10",
)]


def is_private_host(url: str) -> bool:
    """
    判断是否组播/内网地址。

    @param url  播放地址
    @retval     True 表示公网探测无意义
    """
    host = up.urlparse(url).hostname or ""
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in n for n in PRIVATE_NETS)


def classify_body(body: bytes) -> tuple[bool, str]:
    """
    判断响应体是否像流媒体。

    @param body  响应前 N 字节
    @retval      (是否存活, 类型标签)
    """
    if not body:
        return False, "empty"

    low = body[:1024].lower()
    if any(h in low for h in PARK_HINT):
        return False, "parked"

    head = body.lstrip()[:16]
    for magic in M3U8_MAGIC:
        if head.startswith(magic) or magic in body[:64]:
            return True, "hls"

    # MPEG-TS：0x47 同步字节 + 188 字节对齐
    if len(body) >= 376:
        for off in range(0, min(4, len(body) - 376)):
            if (body[off] == 0x47
                    and body[off + 188] == 0x47
                    and body[off + 376] == 0x47):
                return True, "mpegts"

    if b"ftyp" in body[:32]:
        return True, "mp4"

    if any(h in low for h in HTML_HINT):
        return False, "html"

    return True, "raw"      # 不确定时放行，交给播放器最终判定


async def probe_one(session: aiohttp.ClientSession,
                    channel: Channel,
                    sem: asyncio.Semaphore,
                    host_sems: dict) -> Channel | None:
    """
    探测单个频道源。

    @param session   复用的 aiohttp 会话
    @param channel   待探测频道
    @param sem       全局并发信号量
    @param host_sems 按域名的并发信号量字典
    @retval          存活则返回原对象（已填 latency_ms），否则 None
    """
    if UDP_RE.match(channel.url):
        channel.latency_ms = -2         # 组播：本地网络专用，不剔除
        return channel

    if is_private_host(channel.url):
        channel.latency_ms = -3         # 内网地址，保留但降权
        channel.weight *= 0.5
        return channel

    host = up.urlparse(channel.url).netloc
    hs = host_sems.setdefault(host, asyncio.Semaphore(P.batch_per_host))

    async with sem, hs:
        t0 = time.perf_counter()
        for attempt in range(P.retries + 1):
            try:
                to = aiohttp.ClientTimeout(connect=P.timeout_connect,
                                           total=P.timeout_read)
                async with session.get(channel.url, timeout=to,
                                       allow_redirects=True, ssl=False) as r:
                    if r.status >= 400:
                        raise RuntimeError(f"HTTP {r.status}")
                    body = await r.content.read(P.head_bytes)

                elapsed = int((time.perf_counter() - t0) * 1000)
                ok, kind = classify_body(body)
                if ok:
                    channel.latency_ms = elapsed
                    if elapsed > P.max_latency_ms:
                        channel.weight *= 0.6       # 慢速源降权
                    return channel
                log.debug("判定失败 [%s] %s -> %s", kind, channel.name, channel.url)
                return None
            except Exception:
                if attempt >= P.retries:
                    return None
                await asyncio.sleep(0.4 * (attempt + 1))
    return None


async def probe_all(channels: list[Channel],
                    concurrency: int | None = None) -> list[Channel]:
    """
    并发探测全部频道，返回存活列表。

    @param channels     待探测列表
    @param concurrency  并发数，默认取配置
    @retval             存活频道列表
    """
    conc = concurrency or P.concurrency
    sem = asyncio.Semaphore(conc)
    host_sems: dict[str, asyncio.Semaphore] = {}

    conn = aiohttp.TCPConnector(limit=conc, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers=CONFIG["headers"]) as s:
        results = await asyncio.gather(
            *(probe_one(s, c, sem, host_sems) for c in channels),
            return_exceptions=True)

    alive = [r for r in results if isinstance(r, Channel)]
    log.info("探测完成: %d/%d 存活", len(alive), len(channels))
    return alive
