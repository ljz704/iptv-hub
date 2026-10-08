# -*- coding: utf-8 -*-
"""
验证北邮 ivi 公开源，补齐缺失卫视。

ivi.bupt.edu.cn 是北京邮电大学的公开 IPTV 源，地址规整：
    http://ivi.bupt.edu.cn/hls/<代号>.m3u8
教育网源，全国可达性较好（实测验证过才写入）。
"""
from __future__ import annotations

import asyncio
import io
import sys
from urllib.parse import urljoin

import aiohttp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UA = 'Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36'
BASE = 'http://ivi.bupt.edu.cn/hls'

# 频道名 -> ivi 代号（常用代号表）
CHANNELS = {
    '江苏卫视': 'jstv',
    '江苏卫视高清': 'jshd',
    '山东卫视': 'sdtv',
    '山东卫视高清': 'sdhd',
    '天津卫视': 'tjtv',
    '天津卫视高清': 'tjhd',
    'CCTV-1': 'cctv1',
    'CCTV-2': 'cctv2',
    'CCTV-3': 'cctv3',
    'CCTV-4': 'cctv4',
    'CCTV-5': 'cctv5',
    'CCTV-5+': 'cctv5p',
    'CCTV-6': 'cctv6',
    'CCTV-7': 'cctv7',
    'CCTV-8': 'cctv8',
    'CCTV-9': 'cctv9',
    'CCTV-10': 'cctv10',
    'CCTV-11': 'cctv11',
    'CCTV-12': 'cctv12',
    'CCTV-13': 'cctv13',
    'CCTV-14': 'cctv14',
    'CCTV-15': 'cctv15',
    '湖南卫视': 'hunan',
    '浙江卫视': 'zhejiang',
    '东方卫视': 'dongfang',
    '北京卫视': 'beijing',
    '广东卫视': 'guangdong',
    '深圳卫视': 'shenzhen',
    '安徽卫视': 'anhui',
    '湖北卫视': 'hubei',
    '河南卫视': 'henan',
    '黑龙江卫视': 'heilongjiang',
    '辽宁卫视': 'liaoning',
    '四川卫视': 'sichuan',
    '重庆卫视': 'chongqing',
    '贵州卫视': 'guizhou',
    '云南卫视': 'yunnan',
    '陕西卫视': 'shaanxi',
    '河北卫视': 'hebei',
    '山西卫视': 'shanxi',
    '吉林卫视': 'jilin',
    '广西卫视': 'guangxi',
    '海南卫视': 'hainan',
    '甘肃卫视': 'gansu',
    '宁夏卫视': 'ningxia',
    '青海卫视': 'qinghai',
    '内蒙古卫视': 'neimenggu',
    '新疆卫视': 'xinjiang',
    '西藏卫视': 'xizang',
    '江西卫视': 'jiangxi',
    '福建东南卫视': 'dongnan',
    '厦门卫视': 'xiamen',
}


async def verify(session, url):
    """验证 m3u8 是否真能播（含分片）。"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12),
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
                               timeout=aiohttp.ClientTimeout(total=12),
                               ssl=False) as r2:
            if r2.status >= 400:
                return False
            d = await r2.content.read(1024)
            return len(d) >= 100
    except Exception:
        return False


async def main():
    conn = aiohttp.TCPConnector(limit=20, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers={'User-Agent': UA}) as s:
        tasks = []
        names = []
        for name, code in CHANNELS.items():
            url = f'{BASE}/{code}.m3u8'
            tasks.append(verify(s, url))
            names.append((name, url))

        results = await asyncio.gather(*tasks)

    alive = [(n, u) for (n, u), ok in zip(names, results) if ok]
    dead = [(n, u) for (n, u), ok in zip(names, results) if not ok]

    print(f'验证 {len(names)} 个 ivi 源: 可用 {len(alive)}，不可用 {len(dead)}\n')
    print('可用频道:')
    for n, u in alive:
        print(f'  {n:16} {u}')
    if dead:
        print(f'\n不可用 {len(dead)} 个:')
        for n, u in dead[:10]:
            print(f'  {n:16} {u}')

    # 写入 live.txt（替换/补充卫视和央视）
    if alive:
        path = 'dist/live.txt'
        lines = open(path, encoding='utf-8').read().splitlines()

        # 已有频道名，避免重复
        existing = set()
        for l in lines:
            if l and not l.startswith('#genre#') and ',' in l:
                existing.add(l.rpartition(',')[0])

        new = [(n, u) for n, u in alive if n not in existing]
        print(f'\n新增 {len(new)} 个（已存在 {len(alive)-len(new)} 个）')

        if new:
            out = []
            for l in lines:
                out.append(l)
            # 分别插入到对应分组
            cctv_new = [(n, u) for n, u in new if n.startswith('CCTV')]
            ws_new = [(n, u) for n, u in new if not n.startswith('CCTV')]

            if cctv_new:
                idx = out.index('#genre#央视') if '#genre#央视' in out else None
                if idx is not None:
                    for i, (n, u) in enumerate(cctv_new):
                        out.insert(idx + 1 + i, f'{n},{u}')
            if ws_new:
                idx = out.index('#genre#卫视') if '#genre#卫视' in out else None
                if idx is not None:
                    for i, (n, u) in enumerate(ws_new):
                        out.insert(idx + 1 + i, f'{n},{u}')

            open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
            print(f'已写入 {path}')


asyncio.run(main())
