# -*- coding: utf-8 -*-
"""
评估配置获取链路的可靠性，找出单点故障。

测试项：
  1. 各 GitHub 镜像的稳定性（多次请求成功率）
  2. 你自己仓库配置的可达性
  3. 直播流域名本身的可用性
  4. 点播接口可用性
"""
from __future__ import annotations

import io
import statistics
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

REPO_PATH = 'ljz704/iptv-hub/main/dist/tvbox.json'

MIRRORS = [
    ('gh-proxy.com', f'https://gh-proxy.com/https://raw.githubusercontent.com/{REPO_PATH}'),
    ('ghproxy.net', f'https://ghproxy.net/https://raw.githubusercontent.com/{REPO_PATH}'),
    ('ghfast.top', f'https://ghfast.top/https://raw.githubusercontent.com/{REPO_PATH}'),
    ('jsdelivr', f'https://cdn.jsdelivr.net/gh/ljz704/iptv-hub@main/dist/tvbox.json'),
    ('github.io', f'https://ljz704.github.io/iptv-hub/tvbox.json'),
    ('raw 直连', f'https://raw.githubusercontent.com/{REPO_PATH}'),
]

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


def test(url, timeout=15):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        return True, (time.time() - t0) * 1000, len(data)
    except Exception as e:
        return False, (time.time() - t0) * 1000, type(e).__name__


print('=' * 70)
print('1. GitHub 镜像稳定性（各试 3 次）')
print('=' * 70)
for name, url in MIRRORS:
    ok = 0
    times = []
    sizes = []
    for _ in range(3):
        success, ms, info = test(url)
        if success:
            ok += 1
            times.append(ms)
            sizes.append(info)
    if ok:
        avg = statistics.mean(times)
        print(f'  {name:14} {ok}/3 成功   平均 {avg:6.0f}ms   {sizes[0]} 字节')
    else:
        print(f'  {name:14} 0/3 失败   全部超时')

print()
print('=' * 70)
print('2. 点播接口可用性')
print('=' * 70)
VOD = [
    ('暴風资源', 'https://bfzyapi.com/api.php/provide/vod/?ac=videolist&wd=测试'),
    ('百度资源', 'https://api.apibdzy.com/api.php/provide/vod/?ac=videolist&wd=测试'),
]
for name, url in VOD:
    success, ms, info = test(url.encode('ascii', 'ignore').decode() and url, timeout=20)
    status = f'{ms:.0f}ms, {info} 字节' if success else f'失败: {info}'
    print(f'  {name:12} {"OK" if success else "FAIL"}  {status}')

print()
print('=' * 70)
print('3. 直播流域名抽样（各取一个源测连通性）')
print('=' * 70)
STREAMS = [
    ('浙江广电', 'http://l.cztvcloud.com/channels/lantian/SXyuyao3/720p.m3u8'),
    ('吉林广电', 'http://stream2.jlntv.cn/live/8a2edf1e-9b6e-4e5c-9d6e-1.m3u8'),
]
for name, url in STREAMS:
    success, ms, info = test(url, timeout=15)
    print(f'  {name:12} {"OK" if success else "FAIL"}  {ms:.0f}ms  {info}')
