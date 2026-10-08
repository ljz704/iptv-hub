# -*- coding: utf-8 -*-
"""
修正误匹配 + 从可用源补齐缺失频道。

问题：find_missing.py 把「Jiangsu Public & News Channel」(江苏公共新闻)
      误匹配成了「江苏卫视」，需要删掉重新找。

思路：从**已经验证可用的域名池**里找（这些域名对你网络可达），
      而不是从全网瞎猜。
"""
from __future__ import annotations

import asyncio
import io
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

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

WANTED = ['江苏卫视', '山东卫视', '天津卫视']


async def fetch(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=40),
                               ssl=False) as r:
            return await r.text(errors='ignore') if r.status == 200 else ''
    except Exception:
        return ''


async def verify(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10),
                               ssl=False, allow_redirects=True) as r:
            if r.status >= 400:
                return False
            body = await r.content.read(16384)
        text = body.decode('utf-8', 'ignore')
        if '#EXTM3U' not in text:
            return False
        seg = next((l.strip() for l in text.splitlines()
                    if l.strip() and not l.startswith('#')), None)
        if not seg:
            return '#EXT-X-TARGETDURATION' in text
        async with session.get(urljoin(url, seg),
                               timeout=aiohttp.ClientTimeout(total=10),
                               ssl=False) as r2:
            if r2.status >= 400:
                return False
            return len(await r2.content.read(1024)) >= 100
    except Exception:
        return False


def extract(text):
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
        print('拉取上游…')
        texts = await asyncio.gather(*(fetch(s, u) for u in SOURCES))
        all_items = []
        for t in texts:
            all_items.extend(extract(t))
        print(f'共 {len(all_items)} 条候选\n')

        # 严格匹配：名称必须正好是「XX卫视」或含「XX卫视 高清」等，排除子频道
        print('严格匹配候选:')
        cands = {}
        for want in WANTED:
            hits = []
            for name, url in all_items:
                n = name.replace(' ', '')
                # 必须包含完整频道名，且不是子频道
                if want not in n:
                    continue
                # 排除：江苏卫视体育、江苏卫视公共 这类
                tail = n.split(want)[-1]
                if tail and not any(k in tail for k in ['高清', 'HD', '1080', '']):
                    continue
                hits.append((name, url))
            cands[want] = hits
            print(f'  {want}: {len(hits)} 个')
            for n, u in hits[:5]:
                print(f'     {n[:28]:30} {urlparse(u).netloc}')

        # 验证
        print('\n验证中（最多每频道试 20 个）…')
        found = {}
        for want, hits in cands.items():
            checked = 0
            for name, url in hits:
                if checked >= 20:
                    break
                checked += 1
                if await verify(s, url):
                    found[want] = (name, url)
                    print(f'  [OK] {want:8} <- {name[:26]}  {url[:70]}')
                    break
            if want not in found:
                print(f'  [--] {want:8} {checked} 个候选全部不可用')

    # 清理误匹配 + 写入
    path = 'dist/live.txt'
    lines = open(path, encoding='utf-8').read().splitlines()
    out = []
    removed = 0
    for l in lines:
        # 删掉误匹配的江苏公共新闻（伪装成江苏卫视那条）
        if l.startswith('江苏卫视,') and 'jiangning-tv' in l:
            removed += 1
            continue
        out.append(l)

    if found:
        # 删掉同名旧条目后追加
        names_new = set(found.keys())
        out2 = []
        for l in out:
            if l and not l.startswith('#genre#') and ',' in l:
                if l.rpartition(',')[0] in names_new:
                    continue
            out2.append(l)
        out = out2

        idx = out.index('#genre#卫视') if '#genre#卫视' in out else None
        if idx is not None:
            for i, (w, (n, u)) in enumerate(found.items()):
                out.insert(idx + 1 + i, f'{w},{u}')

    open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f'\n删除误匹配 {removed} 条，补齐 {len(found)} 个频道')


asyncio.run(main())
