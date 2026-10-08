# -*- coding: utf-8 -*-
"""批量试探候选源的常见文件路径，找出真正可用的地址。"""
import asyncio
import io
import re
import sys

import aiohttp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

M = 'https://gh-proxy.com/https://raw.githubusercontent.com'

# 每个仓库试探多个常见路径
REPOS = {
    'best-fan/iptv-sources': ('main', [
        'tv.m3u', 'iptv.m3u', 'live.m3u', 'index.m3u',
        'output/tv.m3u', 'dist/tv.m3u', 'm3u/tv.m3u',
        'sources/cn.m3u', 'China.m3u', 'chinese.m3u',
    ]),
    'jiandantv/IPTV2025': ('main', [
        'iptv.m3u', 'tv.m3u', 'live.m3u', 'IPTV.m3u',
        'output/iptv.m3u', 'dist/iptv.m3u', 'm3u/iptv.m3u',
    ]),
    'imDazui/Tvlist-awesome-m3u-m3u8': ('master', [
        'm3u/国内电视台.m3u', 'm3u/国内电视.m3u', 'm3u/china.m3u',
        'm3u/iptv.m3u', '国内电视台.m3u', 'tv.m3u',
    ]),
    'vbskycn/iptv': ('master', [
        'tv/iptv4.m3u', 'tv/iptv6.m3u', 'tv/iptv.txt',
        'iptv.m3u', 'tv.m3u', 'output/iptv4.m3u',
    ]),
    'YueChan/Live': ('main', [
        'IPTV.m3u', 'tv.m3u', 'live.m3u',
    ]),
}

CCTV_RE = re.compile(r'CCTV[-_\s]?(\d{1,2})', re.I)


async def probe(session, repo, branch, path):
    url = f'{M}/{repo}/{branch}/{path}'
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25),
                               ssl=False) as r:
            if r.status != 200:
                return None
            text = await r.text(errors='ignore')
            if len(text) < 100:
                return None
            names = re.findall(r'#EXTINF[^\n]*,(.+)$', text, re.M)
            cctv = {int(m.group(1)) for n in names
                    if (m := CCTV_RE.search(n))}
            return {
                'url': url, 'chans': len(names),
                'cctv': len(cctv),
                'weishi': sum(1 for n in names if '卫视' in n),
                'bytes': len(text),
            }
    except Exception:
        return None


async def main():
    conn = aiohttp.TCPConnector(limit=12, ssl=False)
    async with aiohttp.ClientSession(connector=conn, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}) as s:
        tasks, meta = [], []
        for repo, (branch, paths) in REPOS.items():
            for p in paths:
                tasks.append(probe(s, repo, branch, p))
                meta.append((repo, p))
        results = await asyncio.gather(*tasks)

    found = []
    for (repo, path), info in zip(meta, results):
        if info:
            print(f'[OK] {repo:34} {path:24} '
                  f'{info["chans"]:5}频道 央视{info["cctv"]:2}/17 卫视{info["weishi"]:3}')
            found.append((repo, path, info))
        # 失败的不打印，太吵

    print(f'\n=== 找到 {len(found)} 个可用源 ===')
    for repo, path, info in sorted(found, key=lambda x: -x[2]['chans']):
        print(f'\n{repo} / {path}')
        print(f'  {info["url"]}')
        print(f'  {info["chans"]} 频道, 央视 {info["cctv"]}/17, 卫视 {info["weishi"]}')


asyncio.run(main())
