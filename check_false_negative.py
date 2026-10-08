# -*- coding: utf-8 -*-
"""核查深度验活是否误杀：抽查被判 no-sync 的源，人工复验。"""
import asyncio
import io
import sys

import aiohttp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 从聚合前的完整列表里找央视/卫视源，用多种方式验证
TEST = [
    ('CCTV-1 综合', 'http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226016/index.m3u8'),
    ('CCTV-1 备用', 'http://223.110.245.147/ott.js.chinamobile.com/PLTV/3/224/3221226799/index.m3u8'),
    ('江苏卫视', 'http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221226537/index.m3u8'),
    ('湖南卫视', 'http://ottrrs.hl.chinamobile.com/PLTV/88888888/224/3221225730/index.m3u8'),
]

UA = 'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36'


async def test_url(session, name, url):
    print(f'\n--- {name} ---')
    print(f'    {url}')
    # 1) 表层：状态码
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12),
                               ssl=False) as r:
            print(f'    HTTP {r.status}  Content-Type: {r.headers.get("Content-Type","?")}')
            body = await r.content.read(4096)
            txt = body.decode('utf-8', 'ignore')
            print(f'    前 80 字符: {txt[:80]!r}')
            if '#EXTM3U' in txt:
                # 是 m3u8，看分片
                lines = [l.strip() for l in txt.splitlines()
                         if l.strip() and not l.startswith('#')]
                if lines:
                    from urllib.parse import urljoin
                    seg = urljoin(url, lines[0])
                    print(f'    首分片: {seg[:90]}')
                    try:
                        async with session.get(seg, timeout=aiohttp.ClientTimeout(total=12),
                                               ssl=False) as r2:
                            d = await r2.content.read(2048)
                            print(f'    分片: HTTP {r2.status}  {len(d)} 字节  '
                                  f'{d[:8].hex()}')
                    except Exception as e:
                        print(f'    分片失败: {type(e).__name__}')
    except Exception as e:
        print(f'    请求失败: {type(e).__name__}: {e}')


async def main():
    conn = aiohttp.TCPConnector(limit=8, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers={'User-Agent': UA}) as s:
        for n, u in TEST:
            await test_url(s, n, u)


asyncio.run(main())
