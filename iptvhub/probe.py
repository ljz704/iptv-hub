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


async def _verify_hls_segment(session, url: str) -> tuple[bool, str]:
    """
    HLS 深度验证：主列表 -> 取分片 -> 真实下载分片。

    普通探测只看响应头，会漏掉"播放列表返回 200 但分片已删除(404)"的源。
    实测 604 条里有 33 条属于这种情况。

    @param session  aiohttp 会话
    @param url      m3u8 地址
    @retval         (是否可用, 说明)
    """
    from urllib.parse import urljoin

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10),
                               ssl=False, allow_redirects=True) as r:
            if r.status >= 400:
                return False, f"HTTP {r.status}"
            body = await r.content.read(16384)
    except Exception as exc:
        return False, type(exc).__name__

    text = body.decode("utf-8", "ignore")
    if "#EXTM3U" not in text and "#EXT-X-" not in text:
        return False, "not-hls"

    # 主列表：取第一个子列表
    if "#EXT-X-STREAM-INF" in text:
        sub = next((ln.strip() for ln in text.splitlines()
                    if ln.strip() and not ln.startswith("#")), None)
        if not sub:
            return False, "no-variant"
        try:
            async with session.get(urljoin(url, sub),
                                   timeout=aiohttp.ClientTimeout(total=10),
                                   ssl=False) as r2:
                if r2.status >= 400:
                    return False, f"sub HTTP {r2.status}"
                text = await r2.text(errors="ignore")
        except Exception as exc:
            return False, "sub-" + type(exc).__name__

    seg = next((ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.startswith("#")), None)
    if not seg:
        if "#EXT-X-TARGETDURATION" in text or "#EXTINF" in text:
            return True, "live-ok"
        return False, "no-segment"

    try:
        async with session.get(urljoin(url, seg),
                               timeout=aiohttp.ClientTimeout(total=10),
                               ssl=False) as r3:
            if r3.status >= 400:
                return False, f"seg HTTP {r3.status}"
            chunk = await r3.content.read(2048)
            if len(chunk) < 100:
                return False, "seg-too-small"
        return True, "deep-ok"
    except Exception as exc:
        return False, "seg-" + type(exc).__name__


async def probe_one(session: aiohttp.ClientSession,
                    channel: Channel,
                    sem: asyncio.Semaphore,
                    host_sems: dict,
                    deep: bool = False,
                    drop_multicast: bool = True) -> Channel | None:
    """
    探测单个频道源。

    @param session         复用的 aiohttp 会话
    @param channel         待探测频道
    @param sem             全局并发信号量
    @param host_sems       按域名的并发信号量字典
    @param deep            True 时对 HLS 源做分片级深度验证
    @param drop_multicast  True 时剔除组播源
    @retval                存活则返回原对象（已填 latency_ms），否则 None

    关于组播：
        udp:// rtp:// igmp:// 这类组播地址需要运营商的 IPTV 专网
        （光猫的 IPTV 口 + VLAN），普通宽带/WiFi 播放必然失败。
        实测当前列表里有 89 条组播源，留着只会让用户点了看不了，
        所以默认剔除；需要时用 drop_multicast=False 保留。
    """
    if UDP_RE.match(channel.url):
        if drop_multicast:
            channel.latency_ms = -2
            log.debug("剔除组播源: %s -> %s", channel.name, channel.url)
            return None
        channel.latency_ms = -2
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
                # 深度模式：HLS 源走分片验证
                if deep and ".m3u8" in channel.url.lower():
                    ok, note = await _verify_hls_segment(session, channel.url)
                    if ok:
                        channel.latency_ms = int((time.perf_counter() - t0) * 1000)
                        return channel
                    log.debug("深度验证失败 [%s] %s", note, channel.name)
                    return None

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
                    concurrency: int | None = None,
                    deep: bool = False,
                    drop_multicast: bool = True) -> list[Channel]:
    """
    并发探测全部频道，返回存活列表。

    @param channels        待探测列表
    @param concurrency     并发数，默认取配置
    @param deep            True 时启用深度验证（下载真实分片），能筛掉"播放列表在
                           但分片已删除"的假活源；代价是慢约 3 倍
    @param drop_multicast  True 时剔除组播源（普通宽带播不了）
    @retval                存活频道列表
    """
    conc = concurrency or P.concurrency
    sem = asyncio.Semaphore(conc)
    host_sems: dict[str, asyncio.Semaphore] = {}

    conn = aiohttp.TCPConnector(limit=conc, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers=CONFIG["headers"]) as s:
        results = await asyncio.gather(
            *(probe_one(s, c, sem, host_sems, deep, drop_multicast)
              for c in channels),
            return_exceptions=True)

    alive = [r for r in results if isinstance(r, Channel)]
    dropped_mc = sum(1 for c in channels if UDP_RE.match(c.url)) \
        if drop_multicast else 0
    log.info("探测完成: %d/%d 存活%s", len(alive), len(channels),
             f"（剔除组播 {dropped_mc} 条）" if dropped_mc else "")
    return alive
