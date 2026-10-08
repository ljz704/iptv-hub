# -*- coding: utf-8 -*-
"""多上游并发抓取，带镜像回退与失败隔离。"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse as up

import aiohttp

from .config import CONFIG, RAW_MIRRORS, UPSTREAMS

log = logging.getLogger("fetcher")


def normalize_url(url: str) -> str:
    """
    规范化 URL：中文域名（IDN）转 punycode。

    实测 TVBox 源里存在 http://我不是.肥猫.live/TV/tvzb.txt 这类中文域名，
    aiohttp 不做 IDN 转码会直接抛异常。

    @param url  原始地址
    @retval     可请求的地址
    """
    try:
        parts = up.urlsplit(url)
        if not parts.hostname:
            return url
        host = parts.hostname.encode("idna").decode("ascii")
        if parts.port:
            host = f"{host}:{parts.port}"
        if parts.username:
            auth = parts.username
            if parts.password:
                auth += f":{parts.password}"
            host = f"{auth}@{host}"
        return up.urlunsplit((parts.scheme, host, parts.path,
                              parts.query, parts.fragment))
    except Exception:
        return url


def mirror_candidates(url: str) -> list[str]:
    """
    为 raw.githubusercontent.com 生成镜像回退链。

    @param url  原始地址
    @retval     候选地址列表（去重，原地址在前）
    """
    url = normalize_url(url)

    if "raw.githubusercontent.com/" not in url:
        return [url]

    path = url.split("raw.githubusercontent.com/", 1)[1]
    out = [url]
    for tpl in RAW_MIRRORS:
        try:
            cand = tpl.format(p=path)
            if cand not in out:
                out.append(cand)
        except Exception:
            continue
    return list(dict.fromkeys(out))


async def get_text(session: aiohttp.ClientSession,
                   url: str,
                   timeout: float = 25.0) -> str | None:
    """
    带镜像回退的 GET 文本。

    @param session  aiohttp 会话
    @param url      目标地址
    @param timeout  总超时秒数
    @retval         正文，全部失败返回 None
    """
    for cand in mirror_candidates(url):
        for attempt in range(2):
            try:
                to = aiohttp.ClientTimeout(total=timeout)
                async with session.get(cand, timeout=to) as r:
                    if r.status != 200:
                        raise RuntimeError(f"HTTP {r.status}")
                    text = await r.text(errors="ignore")
                    if len(text) < 32:
                        raise RuntimeError("body too short")
                    log.info("ok  %s (%d bytes)", cand, len(text))
                    return text
            except Exception as exc:
                log.warning("fail %s attempt=%d: %s", cand, attempt + 1, exc)
                await asyncio.sleep(0.8 * (attempt + 1))
    return None


async def fetch_all() -> dict[str, tuple[str, str]]:
    """
    并发拉取所有上游，单点失败不影响整体。

    @retval  {上游名: (正文, 实际命中的地址)}
             带上命中地址是因为 TVBox JSON 里存在 ./list.txt 这类相对路径，
             需要按订阅自身的地址展开。
    """
    conn = aiohttp.TCPConnector(limit=32, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers=CONFIG["headers"]) as s:
        tasks = {u.name: asyncio.create_task(get_text(s, u.url))
                 for u in UPSTREAMS if u.enabled}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    out: dict[str, tuple[str, str]] = {}
    for name, res in zip(tasks.keys(), results):
        if isinstance(res, str) and res.strip():
            # 记录原始上游地址作为 base（不用镜像地址，镜像路径会破坏相对路径语义）
            up_obj = next((u for u in UPSTREAMS if u.name == name), None)
            base = up_obj.url if up_obj else ""
            out[name] = (res, base)
        else:
            log.error("上游 %s 抓取失败: %r", name, res)
    log.info("抓取完成: %d/%d 个上游成功", len(out), len(tasks))
    return out
