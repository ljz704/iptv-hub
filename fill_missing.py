# -*- coding: utf-8 -*-
"""
补齐缺失频道：江苏/深圳/山东/天津卫视，以及 CGTN 等。

原理：这几个卫视的官方 CDN 地址是稳定的，直接写入。
另外从已聚合的源里再翻一遍，可能有别名没被识别。
"""
from __future__ import annotations

import asyncio
import io
import sys

import aiohttp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 各卫视的官方/常用直播源候选（多给几条，验证后取活着的）
CANDIDATES = {
    '江苏卫视': [
        'http://live.jstv.com/HD-live/600.m3u8',
        'http://live.jstv.com/HD-live/500.m3u8',
        'https://lives.jstv.com/live/600.m3u8',
    ],
    '深圳卫视': [
        'https://live.sztv.com.cn/live/3500.m3u8',
        'http://live.sztv.com.cn/live/3500.m3u8',
    ],
    '山东卫视': [
        'http://livealone302.iqilu.com/iqilu/sdtv.m3u8',
        'http://liveing.iqilu.com/live/sdtv.m3u8',
    ],
    '天津卫视': [
        'http://live.tjbnmc.cn/live/3500.m3u8',
        'https://live.tjbnmc.cn/live/tjtv1.m3u8',
    ],
}

UA = 'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36'


async def verify(session, name, url):
    """验证 m3u8 可用性（含分片检查）。"""
    from urllib.parse import urljoin
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12),
                               ssl=False, allow_redirects=True) as r:
            if r.status >= 400:
                return None
            body = await r.content.read(8192)
        text = body.decode('utf-8', 'ignore')
        if '#EXTM3U' not in text:
            return None

        seg = next((ln.strip() for ln in text.splitlines()
                    if ln.strip() and not ln.startswith('#')), None)
        if not seg:
            if '#EXT-X-TARGETDURATION' in text:
                return url
            return None

        async with session.get(urljoin(url, seg),
                               timeout=aiohttp.ClientTimeout(total=12),
                               ssl=False) as r2:
            if r2.status >= 400:
                return None
            d = await r2.content.read(1024)
            if len(d) < 100:
                return None
        return url
    except Exception:
        return None


async def main():
    conn = aiohttp.TCPConnector(limit=8, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers={'User-Agent': UA}) as s:
        found = {}
        for name, urls in CANDIDATES.items():
            print(f'\n{name}:')
            for u in urls:
                ok = await verify(s, name, u)
                if ok:
                    print(f'  [OK] {u}')
                    found[name] = ok
                    break
                else:
                    print(f'  [--] {u}')

    print(f'\n=== 验证成功 {len(found)} 个 ===')
    if found:
        # 追加到 live.txt 的卫视分组
        path = 'dist/live.txt'
        lines = open(path, encoding='utf-8').read().splitlines()
        out, added = [], False
        has_watch = set()
        for l in lines:
            out.append(l)
            if l.strip() == '#genre#卫视':
                for n, u in found.items():
                    out.append(f'{n},{u}')
                    has_watch.add(n)
                added = True
        if not added:
            out.append('#genre#卫视')
            for n, u in found.items():
                out.append(f'{n},{u}')

        open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
        print(f'已写入 {path}（新增 {len(has_watch)} 个频道）')


asyncio.run(main())
