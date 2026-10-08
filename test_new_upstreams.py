# -*- coding: utf-8 -*-
"""
实测新候选上游源的可用性与规模。

评估维度：
  1. 能否下载（走 gh-proxy.com 镜像）
  2. 解析出多少频道
  3. 央视频道覆盖情况（CCTV-1~17 命中几个）
  4. 卫视覆盖情况
"""
import asyncio
import io
import re
import sys

import aiohttp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

MIRROR = 'https://gh-proxy.com/https://raw.githubusercontent.com'

CANDIDATES = [
    ('best-fan/iptv-sources',
     f'{MIRROR}/best-fan/iptv-sources/main/tv.m3u', 'm3u'),
    ('best-fan (ipv6)',
     f'{MIRROR}/best-fan/iptv-sources/main/tv6.m3u', 'm3u'),
    ('vbskycn/iptv',
     f'{MIRROR}/vbskycn/iptv/master/tv/iptv4.m3u', 'm3u'),
    ('vbskycn/iptv (ipv6)',
     f'{MIRROR}/vbskycn/iptv/master/tv/iptv6.m3u', 'm3u'),
    ('jiandantv/IPTV2025',
     f'{MIRROR}/jiandantv/IPTV2025/main/iptv.m3u', 'm3u'),
    ('imDazui/Tvlist',
     f'{MIRROR}/imDazui/Tvlist-awesome-m3u-m3u8/master/m3u/%E5%9B%BD%E5%86%85%E7%94%B5%E8%A7%86%E5%8F%B0.m3u', 'm3u'),
    ('YueChan/Live',
     f'{MIRROR}/YueChan/Live/main/IPTV.m3u', 'm3u'),
    ('iptv-org 全部中国',
     f'{MIRROR}/iptv-org/iptv/master/streams/cn.m3u', 'm3u'),
]

# 已有上游里质量最好的 TVBox 配置
TVBOX_CANDIDATES = [
    ('gaotianliuyun/gao 0821',
     f'{MIRROR}/gaotianliuyun/gao/master/0821.json'),
    ('gaotianliuyun/gao 0608',
     f'{MIRROR}/gaotianliuyun/gao/master/0608.json'),
    ('PizazzGY/TVBox',
     f'{MIRROR}/PizazzGY/TVBox/main/api.json'),
    ('YuanHsing/TVBox',
     f'{MIRROR}/YuanHsing/TVBox/main/ys.json'),
]

URL_RE = re.compile(r'^(https?|rtmp|rtsp|rtp|udp|igmp)://', re.I)
CCTV_RE = re.compile(r'CCTV[-_\s]?(\d{1,2})', re.I)


async def check(session, name, url, kind):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=40),
                               ssl=False) as r:
            if r.status != 200:
                return name, url, None, f'HTTP {r.status}'
            text = await r.text(errors='ignore')
    except Exception as e:
        return name, url, None, type(e).__name__

    if kind == 'm3u':
        # 统计频道
        chans = re.findall(r'#EXTINF[^\n]*\n(?:#[^\n]*\n)*([^\n#]+)', text)
        names = re.findall(r'#EXTINF[^\n]*,(.+)$', text, re.M)
        cctv = set()
        for n in names:
            m = CCTV_RE.search(n)
            if m:
                cctv.add(int(m.group(1)))
        return name, url, {
            'bytes': len(text),
            'chans': len(names),
            'cctv': sorted(cctv),
            'weishi': sum(1 for n in names if '卫视' in n),
        }, 'ok'
    return name, url, {'bytes': len(text)}, 'ok'


async def main():
    print('=== 直接 m3u 源 ===\n')
    conn = aiohttp.TCPConnector(limit=8, ssl=False)
    async with aiohttp.ClientSession(connector=conn, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}) as s:
        tasks = [check(s, n, u, k) for n, u, k in CANDIDATES]
        results = await asyncio.gather(*tasks)

    good = []
    for name, url, info, note in results:
        if info:
            c = len(info.get('cctv', []))
            print(f'  [OK] {name:24} {info["chans"]:5} 频道  '
                  f'央视 {c:2}/17  卫视 {info.get("weishi", 0):3}')
            if info['chans'] > 30:
                good.append((name, url))
        else:
            print(f'  [--] {name:24} {note}')

    print('\n=== TVBox 配置源 ===\n')
    async with aiohttp.ClientSession(connector=conn, headers={
            'User-Agent': 'Mozilla/5.0'}) as s:
        tasks = [check(s, n, u, 'json') for n, u in TVBOX_CANDIDATES]
        results2 = await asyncio.gather(*tasks)

    for name, url, info, note in results2:
        if info:
            print(f'  [OK] {name:24} {info["bytes"]:8} 字节')
            good.append((name, url))
        else:
            print(f'  [--] {name:24} {note}')

    print(f'\n可用候选: {len(good)} 个')


asyncio.run(main())
