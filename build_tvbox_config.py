# -*- coding: utf-8 -*-
"""
生成最终交付给 TVBox 的配置文件。

与 dist/tvbox.json 的区别：
  1. sites 里补上实测可用的真实接口（暴風/百度），而非空 ext
  2. spider 使用国内可达的镜像地址
  3. lives 指向聚合后的直播源
  4. 同时输出一份 m3u 供不支持 json 的播放器用

产物：
  dist/tvbox.json      给 TVBox / 影视仓 用的完整配置
  dist/live_multi.m3u  带备用源的直播列表
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path('.')
DIST = ROOT / 'dist'

# ---------------------------------------------------------------- 实测可用的点播源
# 由 probe_vod_sites.py 实测得出（关键词「庆余年」返回结果）
VOD_SITES = [
    {
        "key": "bfzy",
        "name": "暴風资源",
        "type": 3,
        "api": "csp_Bfzy",
        "searchable": 1,
        "quickSearch": 1,
        "filterable": 1,
        "ext": "https://bfzyapi.com/api.php/provide/vod/",
    },
    {
        "key": "bdzy",
        "name": "百度资源",
        "type": 3,
        "api": "csp_Bdzy",
        "searchable": 1,
        "quickSearch": 1,
        "filterable": 1,
        "ext": "https://api.apibdzy.com/api.php/provide/vod/",
    },
]

# spider 包（国内镜像）。
# 实测（小文件、3 次重试）：
#   gh-proxy.com   3/3 成功，0.6~1.5s   <- 最快最稳
#   ghproxy.net    3/3 成功，1.7~3.4s
#   ghfast.top     2/3 成功（偶发 SSL 握手超时）
# 注意：大文件下载场景 ghfast.top 反而最快（1620 KB/s），镜像选择要分场景。
MIRROR = "gh-proxy.com"
SPIDER = (f"https://{MIRROR}/https://raw.githubusercontent.com/"
          "gaotianliuyun/gao/master/jar/fan.txt;md5;6c4ab3a9d232164c75534f9060506ee5")


def main():
    # 读现有配置，保留点播源里其它可用的
    cfg_path = DIST / 'tvbox.json'
    existing = {}
    if cfg_path.exists():
        existing = json.loads(cfg_path.read_text('utf-8'))

    old_sites = existing.get('sites', [])

    # 合并：实测源优先，其余保留但标记为需要 spider
    merged = list(VOD_SITES)
    seen_names = {s['name'] for s in VOD_SITES}
    for s in old_sites:
        if s.get('name') in seen_names:
            continue
        merged.append(s)

    # 直播源地址：
    #   本地部署用相对路径 ./live_multi.m3u 没问题，
    #   但推送到 GitHub 后电视端拉的是远程配置，必须给绝对地址。
    #   通过环境变量 LIVE_M3U_BASE 控制，默认走 GitHub raw 镜像。
    base = os.getenv(
        'LIVE_M3U_BASE',
        'https://gh-proxy.com/https://raw.githubusercontent.com/'
        'ljz704/iptv-hub/main/dist')
    live_url = f"{base.rstrip('/')}/live_multi.m3u"

    final = {
        "spider": SPIDER,
        "wallpaper": "https://bing.img.run/1920x1080.php",
        "lives": [
            {
                "name": "聚合直播",
                "type": 0,
                "url": live_url,
                "playerType": 1,
            }
        ],
        "sites": merged,
    }

    out = DIST / 'tvbox.json'
    out.write_text(json.dumps(final, ensure_ascii=False, indent=2), 'utf-8')

    print(f'已生成 {out}')
    print(f'  点播源: {len(merged)} 个（其中实测可用 {len(VOD_SITES)} 个）')
    print(f'  直播地址: {live_url}')
    print(f'  spider: {SPIDER[:70]}...')
    print()
    print('实测可用的点播源:')
    for s in VOD_SITES:
        print(f"  {s['name']:10} {s['ext']}")


if __name__ == '__main__':
    main()
