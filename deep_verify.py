# -*- coding: utf-8 -*-
"""
深度验活：比 probe.py 更严格的检查。

probe.py 只看 HTTP 响应头 + 前 4KB 特征，会漏掉"返回 200 但实际播不了"的源。

本脚本对 m3u8 源做**两级验证**：
  1. GET 主播放列表，确认返回 #EXTM3U
  2. 从播放列表里取第一个分片（.ts/.m4s），确认该分片真的能下载
  这种源才是真正能播的。

对于直连 TS 流：读足够字节确认 0x47 同步字节持续出现。

用法：python deep_verify.py [dist/live.txt]
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
import time
from pathlib import Path

import aiohttp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

TIMEOUT = 12
CONCURRENCY = 60
UA = 'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36'


def is_m3u8(url: str) -> bool:
    return '.m3u8' in url.lower()


async def verify_m3u8(session, url):
    """
    验证 HLS 流：主列表 -> 取分片 -> 下载分片。
    返回 (是否可用, 说明)
    """
    try:
        # 第一级：拿主播放列表
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                               ssl=False, allow_redirects=True) as r:
            if r.status >= 400:
                return False, f'HTTP {r.status}'
            body = await r.content.read(16384)
    except Exception as e:
        return False, type(e).__name__

    text = body.decode('utf-8', 'ignore')
    if '#EXTM3U' not in text and '#EXT-X-' not in text:
        return False, 'not-hls'

    # 如果是主列表（含多个码率），取第一个子列表
    if '#EXT-X-STREAM-INF' in text:
        sub = None
        for ln in text.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith('#'):
                sub = ln
                break
        if not sub:
            return False, 'no-variant'
        try:
            from urllib.parse import urljoin
            sub_url = urljoin(url, sub)
            async with session.get(sub_url,
                                   timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                                   ssl=False) as r2:
                if r2.status >= 400:
                    return False, f'sub HTTP {r2.status}'
                text = await r2.text(errors='ignore')
        except Exception as e:
            return False, 'sub-' + type(e).__name__

    # 第二级：找分片地址
    seg = None
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            seg = ln
            break
    if not seg:
        # 可能是纯直播流，没有分片但有 #EXT-X-TARGETDURATION
        if '#EXT-X-TARGETDURATION' in text or '#EXTINF' in text:
            return True, 'live-ok'
        return False, 'no-segment'

    # 第三级：真的下载分片
    from urllib.parse import urljoin
    seg_url = urljoin(url, seg)
    try:
        async with session.get(seg_url,
                               timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                               ssl=False) as r3:
            if r3.status >= 400:
                return False, f'seg HTTP {r3.status}'
            chunk = await r3.content.read(2048)
            if len(chunk) < 100:
                return False, 'seg-too-small'
        return True, 'ok'
    except Exception as e:
        return False, 'seg-' + type(e).__name__


async def verify_ts(session, url):
    """验证直连 TS/FLV 流：持续读，确认同步字节。"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                               ssl=False) as r:
            if r.status >= 400:
                return False, f'HTTP {r.status}'
            data = await r.content.read(8192)
    except Exception as e:
        return False, type(e).__name__

    if len(data) < 500:
        return False, 'too-small'
    # TS 同步字节：连续三个 0x47 间隔 188
    hits = sum(1 for off in range(min(300, len(data) - 376))
               if data[off] == 0x47 and data[off + 188] == 0x47
               and data[off + 376] == 0x47)
    if hits > 0:
        return True, 'ts-ok'
    return False, 'no-sync'


async def check(session, sem, name, url):
    async with sem:
        if is_m3u8(url):
            ok, note = await verify_m3u8(session, url)
        elif url.startswith(('udp://', 'rtp://', 'igmp://', 'rtp2://')):
            # 组播源：需要运营商 IPTV 专网（光猫 IPTV 口 + VLAN），
            # 普通宽带/WiFi 播放必然失败。实测列表里有 89 条，
            # 留着只会让用户点了看不了，直接判定不可用。
            return name, url, False, 'multicast'
        else:
            ok, note = await verify_ts(session, url)
        return name, url, ok, note


async def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist/live.txt')
    items = []
    group = None
    for line in path.read_text('utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#genre#'):
            group = line[7:].strip()
        elif ',' in line:
            name, _, url = line.rpartition(',')
            items.append((group or '其他', name, url))

    print(f'待验证: {len(items)} 条')
    print(f'并发: {CONCURRENCY}, 超时: {TIMEOUT}s')
    print('（HLS 源会下载实际分片，比表层探测严格）\n')

    sem = asyncio.Semaphore(CONCURRENCY)
    conn = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False, ttl_dns_cache=300)
    t0 = time.time()
    async with aiohttp.ClientSession(connector=conn,
                                     headers={'User-Agent': UA}) as s:
        results = await asyncio.gather(
            *(check(s, sem, n, u) for _, n, u in items))

    alive, dead = [], []
    reasons = {}
    for (g, n, u), (_, _, ok, note) in zip(items, results):
        reasons[note] = reasons.get(note, 0) + 1
        if ok:
            alive.append((g, n, u))
        else:
            dead.append((g, n, u))

    print(f'耗时 {time.time()-t0:.0f}s')
    print(f'可用: {len(alive)}   不可用: {len(dead)}   '
          f'存活率 {len(alive)/len(items):.1%}')
    print()
    print('失败原因统计:')
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f'    {c:5d}  {r}')

    # 写回只保留可用的
    if '--write' in sys.argv:
        from collections import defaultdict
        by_group = defaultdict(list)
        for g, n, u in alive:
            by_group[g].append((n, u))
        ORDER = ['央视', '卫视', '港澳台', '影视', '体育', '少儿',
                 '新闻', '纪录', '音乐', '地方', '国际', '其他']
        lines = []
        for g in ORDER + [x for x in by_group if x not in ORDER]:
            if g not in by_group:
                continue
            lines.append(f'#genre#{g}')
            for n, u in sorted(by_group[g]):
                lines.append(f'{n},{u}')
        path.write_text('\n'.join(lines) + '\n', 'utf-8')
        print(f'\n已写回 {path}（{len(alive)} 条）')


asyncio.run(main())
