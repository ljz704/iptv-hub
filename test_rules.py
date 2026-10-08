# -*- coding: utf-8 -*-
"""单元测试：验证噪声清洗与过滤规则。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

from iptvhub.filtering import is_radio, is_likely_channel, looks_like_song
from iptvhub.normalize import strip_noise, canonical

CASES = [
    ('江苏卫视NOT24/7', '江苏卫视'),
    ('蓬安新闻综合NOT24/7', '蓬安新闻综合'),
    ('北京财经NOT24/7', '北京财经'),
    ('山东体育GEO-BLOCKED', '山东体育'),
    ('CCTV-10576I', None),
    ('广州综合HD', '广州综合'),
    ('湖南卫视高清', '湖南卫视'),
    ('CCTV-1综合', 'CCTV-1'),
    ('中央1台', 'CCTV-1'),
    ('ShandongTVSportsChannel.cn@SD', None),
]

print('=== strip_noise / canonical 测试 ===')
for raw, expect in CASES:
    got = strip_noise(raw)
    can = canonical(raw)
    flag = ''
    if expect is not None and got != expect:
        flag = f'  <-- 期望 {expect}'
    print(f'  {raw:34} -> strip={got:22} canon={can}{flag}')

print()
print('=== 电台识别 ===')
for n in ['海南旅游广播', '温州私家车音乐广播FM100.3', 'CNR文艺之声',
          'KFM981', 'CCTV-1', '湖南卫视', '北京广播电视台', 'CITYFM|城市广播']:
    print(f'  {n:28} is_radio={is_radio(n)}')

print()
print('=== 歌曲形态 ===')
for n in ['卫兰-就算世界无童话', '陈奕迅-富士山下', 'CCTV-1',
          '湖南卫视', 'MADONNA|LIVINGFORLOVE']:
    print(f'  {n:28} song={looks_like_song(n)}')

print()
print('=== 名字合法性 ===')
for n in ['CCTV-10576I', 'CCTV-1', '叹香菱', '往事只能回味',
          '湖南卫视', 'BEYONCE.KNOWLES-HALO']:
    print(f'  {n:28} ok={is_likely_channel(n)}')
