# -*- coding: utf-8 -*-
"""
生成 TVBox 真正支持的直播列表。

问题背景：
    之前输出的 live_multi.m3u 用自定义标签 #EXTM3U-FALLBACK 承载备用源，
    但 TVBox 不认识这个标签（标准播放器会跳过所有不认识的 # 行），
    导致每个频道实际只有一个源，主源挂了就无法播放。

正确做法：
    TVBox / 影视仓 对同名频道会做**故障转移**（failover）——
    即 m3u 里同名频道出现多次时，播放器按顺序尝试。

    所以应该输出：

        #EXTINF:-1 tvg-name="东方卫视" group-title="卫视",东方卫视
        http://主源
        #EXTINF:-1 tvg-name="东方卫视" group-title="卫视",东方卫视
        http://备用1
        #EXTINF:-1 tvg-name="东方卫视" group-title="卫视",东方卫视
        http://备用2

    播放器点一次「东方卫视」，内部会依次试 3 个地址。

本脚本产出：
    dist/live.m3u        同名重复，供 TVBox 故障转移  ← 主推
    dist/live_multi.m3u  保留 FALLBACK 标签，供自研播放器用
    dist/live.txt        频道名,url（同名重复）
"""
from __future__ import annotations

import io
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DIST = Path('dist')

GROUP_ORDER = ['央视', '卫视', '港澳台', '影视', '体育', '少儿',
               '新闻', '纪录', '音乐', '地方', '国际', '其他']


def load_items(path: Path):
    """读 live.txt -> [(group, name, url)]"""
    items = []
    group = '其他'
    for line in path.read_text('utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#genre#'):
            group = line[7:].strip()
        elif ',' in line:
            name, _, url = line.rpartition(',')
            items.append((group, name.strip(), url.strip()))
    return items


def main():
    items = load_items(DIST / 'live.txt')
    print(f'读入 {len(items)} 条')

    # 按 (分组, 频道名) 聚合所有源，保序
    grouped: "OrderedDict[str, OrderedDict[str, list[str]]]" = OrderedDict()
    for g, n, u in items:
        grouped.setdefault(g, OrderedDict())
        grouped[g].setdefault(n, [])
        if u not in grouped[g][n]:
            grouped[g][n].append(u)

    # 统计
    total_ch = sum(len(v) for v in grouped.values())
    multi_ch = sum(1 for v in grouped.values()
                   for urls in v.values() if len(urls) > 1)
    total_urls = sum(len(urls) for v in grouped.values()
                     for urls in v.values())
    print(f'频道 {total_ch} 个，其中多源 {multi_ch} 个，总源数 {total_urls}\n')

    # ---- 1. 标准 m3u：同名重复，供 TVBox 故障转移 ----
    lines = ['#EXTM3U']
    for g in GROUP_ORDER + [x for x in grouped if x not in GROUP_ORDER]:
        if g not in grouped:
            continue
        for name, urls in grouped[g].items():
            for u in urls:
                lines.append(
                    f'#EXTINF:-1 tvg-name="{name}" group-title="{g}",{name}')
                lines.append(u)

    (DIST / 'live.m3u').write_text('\n'.join(lines) + '\n', 'utf-8')
    print(f'✓ live.m3u            {total_urls} 条（同名重复，TVBox 自动故障转移）')

    # ---- 2. 带 FALLBACK 的多源格式（自研播放器用）----
    mlines = ['#EXTM3U']
    for g in GROUP_ORDER + [x for x in grouped if x not in GROUP_ORDER]:
        if g not in grouped:
            continue
        for name, urls in grouped[g].items():
            mlines.append(
                f'#EXTINF:-1 tvg-name="{name}" group-title="{g}" '
                f'source-count="{len(urls)}",{name}')
            if len(urls) > 1:
                mlines.append('#EXTM3U-FALLBACK:' + '|'.join(urls[1:]))
            mlines.append(urls[0])

    (DIST / 'live_multi.m3u').write_text('\n'.join(mlines) + '\n', 'utf-8')
    print(f'✓ live_multi.m3u      {total_ch} 个频道（带 FALLBACK 扩展）')

    # ---- 3. txt 格式：同名重复 ----
    tlines = []
    for g in GROUP_ORDER + [x for x in grouped if x not in GROUP_ORDER]:
        if g not in grouped:
            continue
        tlines.append(f'#genre#{g}')
        for name, urls in grouped[g].items():
            for u in urls:
                tlines.append(f'{name},{u}')

    (DIST / 'live.txt').write_text('\n'.join(tlines) + '\n', 'utf-8')
    print(f'✓ live.txt            {total_urls} 条')

    # ---- 报告 ----
    print('\n多源频道 Top 15（这些频道最不容易挂）:')
    all_multi = [(g, n, len(u)) for g, v in grouped.items()
                 for n, u in v.items() if len(u) > 1]
    for g, n, c in sorted(all_multi, key=lambda x: -x[2])[:15]:
        print(f'  {c} 源  [{g}] {n}')


main()
