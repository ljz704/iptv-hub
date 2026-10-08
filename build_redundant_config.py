# -*- coding: utf-8 -*-
"""
生成多通道冗余的配置，规避单点故障。

问题：
    电视端只填一个配置地址，如果那个 GitHub 镜像挂了，整个 TVBox 就没源了。
    实测各镜像可用性随时变化（raw 直连时通时不通，github.io 完全不通）。

方案：
    TVBox 支持多仓/多订阅配置（JSON 里 urls 数组），
    但更通用的是直接生成**多份配置**，让用户按需切换。

    本脚本生成：
      dist/tvbox.json          主配置（raw 直连，最快）
      dist/tvbox-backup1.json  备用1（ghfast.top）
      dist/tvbox-backup2.json  备用2（ghproxy.net）
      dist/tvbox-backup3.json  备用3（jsdelivr）
      dist/mirrors.txt         所有可用地址清单（出问题时可查）

用法：python build_redundant_config.py
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DIST = Path('dist')
REPO = 'ljz704/iptv-hub'
BRANCH = 'main'

# 镜像通道（按实测速度排序：raw 最快，github.io 不可用故排除）
MIRRORS = [
    ('raw', 'https://raw.githubusercontent.com/{repo}/{branch}/dist', '直连，最快'),
    ('ghfast', 'https://ghfast.top/https://raw.githubusercontent.com/{repo}/{branch}/dist', '镜像，稳定'),
    ('ghproxy-net', 'https://ghproxy.net/https://raw.githubusercontent.com/{repo}/{branch}/dist', '镜像，备用'),
    ('jsdelivr', 'https://cdn.jsdelivr.net/gh/{repo}@{branch}/dist', 'CDN，较慢'),
]


def main():
    src = DIST / 'tvbox.json'
    if not src.exists():
        print('错误：dist/tvbox.json 不存在，先运行 build_tvbox_config.py')
        return

    base = json.loads(src.read_text('utf-8'))

    lines = []
    lines.append('IPTV 配置地址清单（一个不通就换下一个）')
    lines.append('=' * 72)
    lines.append('')

    for i, (name, tpl, note) in enumerate(MIRRORS):
        base_url = tpl.format(repo=REPO, branch=BRANCH)
        cfg = dict(base)

        # 直播地址改成对应镜像
        cfg['lives'] = [
            {
                'name': '聚合直播',
                'type': 0,
                'url': f'{base_url}/live.m3u',
                'playerType': 1,
            }
        ]

        if i == 0:
            out = DIST / 'tvbox.json'
            label = '【主配置】'
        else:
            out = DIST / f'tvbox-backup{i}.json'
            label = f'【备用{i}】'

        out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), 'utf-8')

        url = f'{base_url}/tvbox.json'
        lines.append(f'{label} {out.name}   ({note})')
        lines.append(f'    {url}')
        lines.append('')

        marker = '★' if i == 0 else ' '
        print(f'{marker} {out.name:24} {url}')

    # 也把 m3u 直接地址列出来（有些播放器只吃 m3u）
    lines.append('-' * 72)
    lines.append('只支持 m3u 的播放器，用这些地址：')
    lines.append('')
    for name, tpl, note in MIRRORS:
        base_url = tpl.format(repo=REPO, branch=BRANCH)
        lines.append(f'    {base_url}/live.m3u')
        lines.append('')

    lines.append('-' * 72)
    lines.append('排查建议：')
    lines.append('  1. 配置加载失败 → 换清单里的下一个地址')
    lines.append('  2. 全部不通 → 检查网络，或等 10 分钟重试（镜像会恢复）')
    lines.append('  3. 频道能加载但播放失败 → 是单个源的问题，不是配置问题')
    lines.append('')

    (DIST / 'mirrors.txt').write_text('\n'.join(lines), 'utf-8')
    print(f'\n已生成 {len(MIRRORS)} 份配置 + mirrors.txt')


main()
