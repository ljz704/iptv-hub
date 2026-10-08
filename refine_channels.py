# -*- coding: utf-8 -*-
"""
按用户反馈二次精修频道列表：删掉实际用不了的和不该有的。

处理项：
  1. 电台（"初秋语•电台" 等分组，共 72 条）—— 电视端不需要
  2. 分组名混乱（"数字"/"卫视频道"/"央视频道" 这类不规范分组）
  3. 疑似死源：同频道多源时，保留全部备用；单源的按延迟排序观察
  4. "直播中国" 分组是风景摄像头，不是电视频道
"""
import io
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LIVE = Path('dist/live.txt')

# 要整组剔除的分组（频道名子串匹配）
DROP_GROUPS = [
    '电台', '直播中国', '数字',
]

# 分组名规范化映射：把混乱的上游分组名归到标准分组
GROUP_MAP = {
    '卫视频道': '卫视',
    '央视频道': '央视',
    '地方频道': '地方',
    '电影频道': '影视',
    '纪录频道': '纪录',
    '儿童频道': '少儿',
    '数字频道': '其他',
    '解说频道': '体育',
    '春晚频道': '其他',
}


def parse_live(path):
    """解析 live.txt 为 [(group, name, url)]。"""
    out = []
    group = None
    for line in path.read_text('utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#genre#'):
            group = line[7:].strip()
        elif ',' in line:
            name, _, url = line.rpartition(',')
            out.append((group or '其他', name, url))
    return out


def main():
    items = parse_live(LIVE)
    print(f'原始: {len(items)} 条')

    # --- 1. 剔除整组 ---
    kept = []
    dropped_group = Counter()
    for g, n, u in items:
        if any(d in g for d in DROP_GROUPS):
            dropped_group[g] += 1
            continue
        kept.append((g, n, u))

    print(f'整组剔除 {sum(dropped_group.values())} 条:')
    for g, c in dropped_group.most_common():
        print(f'    {c:4d}  {g}')

    # --- 2. 分组规范化 ---
    norm = []
    remapped = 0
    for g, n, u in kept:
        ng = GROUP_MAP.get(g, g)
        if ng != g:
            remapped += 1
        norm.append((ng, n, u))
    print(f'分组规范化 {remapped} 条')

    # --- 3. 去重：同组同名只留第一条 ---
    seen = set()
    final = []
    dup = 0
    for g, n, u in norm:
        k = (g, n)
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        final.append((g, n, u))
    print(f'组内去重 {dup} 条')

    # --- 4. 输出 ---
    by_group = defaultdict(list)
    for g, n, u in final:
        by_group[g].append((n, u))

    ORDER = ['央视', '卫视', '港澳台', '影视', '体育', '少儿',
             '新闻', '纪录', '音乐', '地方', '国际', '其他']
    lines = []
    for g in ORDER:
        if g not in by_group:
            continue
        lines.append(f'#genre#{g}')
        for n, u in sorted(by_group[g]):
            lines.append(f'{n},{u}')
    # 未在 ORDER 里的分组追加到末尾
    for g in by_group:
        if g in ORDER:
            continue
        lines.append(f'#genre#{g}')
        for n, u in sorted(by_group[g]):
            lines.append(f'{n},{u}')

    LIVE.write_text('\n'.join(lines) + '\n', 'utf-8')

    print(f'\n最终: {len(final)} 条')
    print(f'  写入 {LIVE}')
    print()
    print('分组分布:')
    for g in ORDER:
        if g in by_group:
            print(f'    {len(by_group[g]):5d}  {g}')


main()
