# -*- coding: utf-8 -*-
"""
从多个上游源里搜出缺失频道的可用地址，并验证。

思路：不猜地址，而是把已知上游全量拉一遍，用关键词匹配找出江苏/深圳/山东/天津卫视，
然后逐条验证（含分片检查），保留真的能用的。
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
from urllib.parse import urljoin

import aiohttp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = 'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36'
M = 'https://gh-proxy.com/https://raw.githubusercontent.com'

SOURCES = [
    f'{M}/vbskycn/iptv/master/tv/iptv4.m3u',
    f'{M}/imDazui/Tvlist-awesome-m3u-m3u8/master/m3u/china.m3u',
    f'{M}/iptv-org/iptv/master/streams/cn.m3u',
    f'{M}/YueChan/Live/main/IPTV.m3u',
]

# 要补的频道：关键词 -> 排除词
WANTED = {
    '江苏卫视': (['江苏卫视', 'Jiangsu'], ['体育', '公共', '城市', '影视', '综艺', '少儿']),
    '深圳卫视': (['深圳卫视', 'Shenzhen'], ['都市', '体育', '财经']),
    '山东卫视': (['山东卫视', 'Shandong', 'SDTV'], ['体育', '齐鲁', '农科', '少儿']),
    '天津卫视': (['天津卫视', 'Tianjin'], ['体育', '都市', '文艺', '少儿']),
}


async def fetch(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=40),
                               ssl=False) as r:
            if r.status != 200:
                return ''
            return await r.text(errors='ignore')
    except Exception:
        return ''


async def verify(session, url):
    """验证 m3u8：主列表 + 分片。"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12),
                               ssl=False, allow_redirects=True) as r:
            if r.status >= 400:
                return False
            body = await r.content.read(16384)
        text = body.decode('utf-8', 'ignore')
        if '#EXTM3U' not in text:
            # 可能是直连 TS
            if len(body) >= 376 and b'\x47' in body[:200]:
                return True
            return False

        if '#EXT-X-STREAM-INF' in text:
            sub = next((l.strip() for l in text.splitlines()
                        if l.strip() and not l.startswith('#')), None)
            if not sub:
                return False
            async with session.get(urljoin(url, sub),
                                   timeout=aiohttp.ClientTimeout(total=12),
                                   ssl=False) as r2:
                if r2.status >= 400:
                    return False
                text = await r2.text(errors='ignore')

        seg = next((l.strip() for l in text.splitlines()
                    if l.strip() and not l.startswith('#')), None)
        if not seg:
            return '#EXT-X-TARGETDURATION' in text or '#EXTINF' in text

        async with session.get(urljoin(url, seg),
                               timeout=aiohttp.ClientTimeout(total=12),
                               ssl=False) as r3:
            if r3.status >= 400:
                return False
            d = await r3.content.read(1024)
            return len(d) >= 100
    except Exception:
        return False


def extract(text):
    """从 m3u 文本提取 (name, url)。"""
    out = []
    name = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF'):
            name = line.split(',')[-1].strip()
        elif line and not line.startswith('#') and name:
            out.append((name, line))
            name = None
    return out


async def main():
    conn = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers={'User-Agent': UA}) as s:
        print('拉取上游源…')
        texts = await asyncio.gather(*(fetch(s, u) for u in SOURCES))

        # 收集候选
        pool = {}
        for t in texts:
            for name, url in extract(t):
                for want, (kws, excludes) in WANTED.items():
                    if any(k in name for k in kws) and not any(e in name for e in excludes):
                        pool.setdefault(want, []).append((name, url))

        print('候选数量:')
        for w, lst in pool.items():
            print(f'  {w}: {len(lst)} 个候选')

        # 逐个验证（每频道最多试 15 个）
        print('\n验证中…')
        result = {}
        for want, lst in pool.items():
            for name, url in lst[:15]:
                if await verify(s, url):
                    result[want] = (name, url)
                    print(f'  [OK] {want}  <- {name}')
                    print(f'       {url}')
                    break
            if want not in result:
                print(f'  [--] {want} 无可用源')

        # 写入
        if result:
            path = 'dist/live.txt'
            lines = open(path, encoding='utf-8').read().splitlines()
            out = []
            inserted = False
            for l in lines:
                out.append(l)
                if l.strip() == '#genre#卫视' and not inserted:
                    for w, (n, u) in result.items():
                        out.append(f'{w},{u}')
                    inserted = True
            if not inserted:
                out.append('#genre#卫视')
                for w, (n, u) in result.items():
                    out.append(f'{w},{u}')
            open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
            print(f'\n已补齐 {len(result)} 个频道到 live.txt')


asyncio.run(main())
