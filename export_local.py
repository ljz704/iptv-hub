# -*- coding: utf-8 -*-
"""
生成「本地可用」的配置包：不依赖 GitHub 也能用。

背景：
    电视/手机端每次打开 TVBox 都去 GitHub 拉配置，有这些风险：
      - GitHub 镜像随时可能挂（实测 github.io 完全不通）
      - 拉取慢（1~2 秒）
      - 断网就用不了

方案：
    把配置和源文件**下载到本地**，TVBox 直接读本地文件。
    源地址本身相对稳定（浙江广电、吉林广电这些 CDN 不会天天换），
    只需要偶尔（几周一次）重新导出。

产出（导出到 export/ 目录）：
    tvbox.json        本地版配置（路径为相对路径）
    live.m3u          直播源列表（490 条）
    live.txt          文本格式，便于手动编辑
    vod_sources.json  点播源
    使用说明.txt        导入步骤

用法：python export_local.py
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path('.')
DIST = ROOT / 'dist'
OUT = ROOT / 'export'


def main():
    OUT.mkdir(exist_ok=True)

    # ---- 1. 读现有配置 ----
    cfg_path = DIST / 'tvbox.json'
    if not cfg_path.exists():
        print('错误：dist/tvbox.json 不存在')
        return
    cfg = json.loads(cfg_path.read_text('utf-8'))

    # ---- 2. 直播地址改为本地文件名（TVBox 支持同目录相对引用）----
    cfg['lives'] = [
        {
            'name': '聚合直播',
            'type': 0,
            'url': 'live.m3u',          # 本地文件名，无 http 前缀
            'playerType': 1,
        }
    ]

    # ---- 3. 移除对远程 spider 的依赖说明（spider 仍需联网，但只拉一次）----
    # spider 是解析器包，TVBox 会缓存，不是每次都拉，可以保留

    # ---- 4. 写出 ----
    (OUT / 'tvbox.json').write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), 'utf-8')

    for name in ['live.m3u', 'live.txt', 'live_multi.m3u', 'vod_sources.json']:
        src = DIST / name
        if src.exists():
            shutil.copy2(src, OUT / name)

    # ---- 5. 统计 ----
    m3u = (OUT / 'live.m3u').read_text('utf-8')
    ch_count = m3u.count('#EXTINF')
    m3u_kb = len(m3u.encode('utf-8')) / 1024

    sites = cfg.get('sites', [])
    usable = [s for s in sites
              if str(s.get('ext', '')).startswith('http')]

    # ---- 6. 使用说明 ----
    readme = f"""IPTV 本地配置包 —— 不依赖 GitHub
================================================

内容：
  tvbox.json          TVBox 配置（{len(sites)} 个点播源）
  live.m3u            直播源列表（{ch_count} 条频道，{m3u_kb:.0f} KB）
  live.txt            同上的文本版，可用记事本编辑
  vod_sources.json    点播源清单

================================================
导入方法（三选一）
================================================

【方法一】TF 卡 / U 盘（推荐，电视用这个）
  1. 把整个 export 文件夹拷到 U 盘
  2. U 盘插电视
  3. TVBox → 设置 → 配置地址 → 填：

       /storage/emulated/0/export/tvbox.json

     或者用文件选择器直接选中 tvbox.json

  注意：安卓路径因机型而异，常见的有：
       /storage/emulated/0/          内部存储
       /storage/XXXX-XXXX/           U 盘/SD卡
     用电视上的文件管理器找到 export 文件夹，看完整路径。

【方法二】手机导入
  1. 把 export 文件夹传到手机存储
  2. TVBox → 设置 → 配置地址 → 选本地文件 → 选中 tvbox.json

【方法三】局域网（电脑开着时）
  1. 电脑上运行：
       cd export
       python -m http.server 8899 --bind 0.0.0.0
  2. TVBox 填：
       http://电脑IP:8899/tvbox.json

================================================
为什么可以本地用？
================================================
  直播源地址（如 l.cztvcloud.com、jlntv.cn）是各地广电的 CDN，
  相对稳定，不会天天变。所以本地保存一份能用很久。

  但免费源终究会失效，建议：
    - 每 2~4 周重新导出一次（跑 python export_local.py）
    - 或者继续用在线地址，让它自动更新

================================================
在线地址（备用，源会自动更新）
================================================
  https://raw.githubusercontent.com/ljz704/iptv-hub/main/dist/tvbox.json
  https://ghfast.top/https://raw.githubusercontent.com/ljz704/iptv-hub/main/dist/tvbox.json
  https://ghproxy.net/https://raw.githubusercontent.com/ljz704/iptv-hub/main/dist/tvbox.json
  https://cdn.jsdelivr.net/gh/ljz704/iptv-hub@main/dist/tvbox.json

  一个不通就换下一个。

================================================
统计
================================================
  直播频道：{ch_count} 条
  点播源：  {len(sites)} 个（其中 {len(usable)} 个有直接接口）
  生成时间：见文件修改时间
"""
    (OUT / '使用说明.txt').write_text(readme, 'utf-8')

    # ---- 7. 报告 ----
    print(f'导出完成 -> {OUT.resolve()}\n')
    print(f'  tvbox.json          {len(sites)} 个点播源')
    print(f'  live.m3u            {ch_count} 条频道 ({m3u_kb:.0f} KB)')
    print(f'  live.txt            文本版')
    print(f'  vod_sources.json    点播清单')
    print(f'  使用说明.txt         导入步骤')
    print()
    total = sum(f.stat().st_size for f in OUT.iterdir() if f.is_file())
    print(f'  总计 {total/1024:.0f} KB —— 整个文件夹拷到 U 盘即可')


main()
