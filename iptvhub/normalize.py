# -*- coding: utf-8 -*-
"""频道名归一化：全角转半角、别名映射、CCTV/卫视编号统一。"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- 基础清洗
def to_halfwidth(s: str) -> str:
    """全角转半角（NFKC 规范化）。"""
    return unicodedata.normalize("NFKC", s)


_NOISE_RE = re.compile(
    # 画质与清晰度标记
    r'(高清|超清|蓝光|4K|8K|1080P|720P|HD|FHD|UHD|标清|\d+P)'
    # 源状态标记（实测 iptv-org cn.m3u 大量出现 NOT24/7、GEO-BLOCKED）
    # 注意：NOT24/7 里的 "/" 在清洗后会被 DASH 规则影响，这里必须显式匹配
    r'|(NOT24[/\-]?7|NOT24H|GEO[\s\-]?BLOCKED|GEOBLOCKED)'
    r'|(DEAD|OFFLINE|备用源|备用|测试源|测试|临时|镜像|重播|时移)'
    r'|(伴音|标清版|高清版)',
    re.I)
# 频道名尾部的 @区域后缀，如 "ShandongTVSportsChannel.cn@SD"
_AT_SUFFIX_RE = re.compile(r'@[A-Za-z0-9_]+$')
_BRACKET_RE = re.compile(r'[\[\]【】()（）<>《》]')
_SPACE_RE = re.compile(r'[\s\u3000]+')
_DASH_RE = re.compile(r'[-_—+·]+')
# 畸形名：CCTV- 后面跟超过 2 位数字（如 CCTV-10576I），判定为脏数据
MALFORMED_CCTV_RE = re.compile(r'^CCTV-\d{3,}', re.I)


def strip_noise(s: str) -> str:
    """
    清洗频道名：去括号、去画质/状态后缀、去空白、统一分隔符、转大写。

    @param s  原始名
    @retval   清洗后的名
    """
    s = to_halfwidth(s).strip()
    s = _BRACKET_RE.sub('', s)
    s = _AT_SUFFIX_RE.sub('', s)      # 去掉 @SD / @HD 等区域标记
    s = _NOISE_RE.sub('', s)
    s = _SPACE_RE.sub('', s)
    s = _DASH_RE.sub('-', s)
    return s.strip('-').upper()


# ---------------------------------------------------------------- 别名表
BUILTIN_ALIASES: dict[str, str] = {
    # ---- 央视 ----
    "CCTV1": "CCTV-1", "CCTV-1综合": "CCTV-1", "中央1台": "CCTV-1",
    "央视一套": "CCTV-1", "CCTV1综合": "CCTV-1", "CCTV-1综合频道": "CCTV-1",
    "CCTV2": "CCTV-2", "中央2台": "CCTV-2", "央视二套": "CCTV-2",
    "CCTV-2财经": "CCTV-2", "CCTV2财经": "CCTV-2",
    "CCTV3": "CCTV-3", "中央3台": "CCTV-3", "综艺频道": "CCTV-3",
    "CCTV-3综艺": "CCTV-3", "CCTV3综艺": "CCTV-3",
    "CCTV4": "CCTV-4", "中央4台": "CCTV-4", "CCTV-4中文国际": "CCTV-4",
    "CCTV4中文国际": "CCTV-4", "国际频道": "CCTV-4",
    "CCTV5": "CCTV-5", "中央5台": "CCTV-5", "体育频道": "CCTV-5",
    "CCTV-5体育": "CCTV-5", "CCTV5体育": "CCTV-5",
    "CCTV5+": "CCTV-5+", "CCTV-5+赛事": "CCTV-5+", "央视体育赛事": "CCTV-5+",
    "CCTV6": "CCTV-6", "中央6台": "CCTV-6", "电影频道": "CCTV-6",
    "CCTV-6电影": "CCTV-6", "CCTV6电影": "CCTV-6",
    "CCTV7": "CCTV-7", "中央7台": "CCTV-7", "CCTV-7国防军事": "CCTV-7",
    "CCTV7国防军事": "CCTV-7", "军事频道": "CCTV-7",
    "CCTV8": "CCTV-8", "中央8台": "CCTV-8", "电视剧频道": "CCTV-8",
    "CCTV-8电视剧": "CCTV-8",
    "CCTV9": "CCTV-9", "中央9台": "CCTV-9", "记录频道": "CCTV-9",
    "CCTV-9纪录": "CCTV-9", "纪录频道": "CCTV-9",
    "CCTV10": "CCTV-10", "中央10台": "CCTV-10", "科教频道": "CCTV-10",
    "CCTV-10科教": "CCTV-10",
    "CCTV11": "CCTV-11", "戏曲频道": "CCTV-11", "CCTV-11戏曲": "CCTV-11",
    "CCTV12": "CCTV-12", "社会与法": "CCTV-12", "CCTV-12社会与法": "CCTV-12",
    "CCTV13": "CCTV-13", "新闻频道": "CCTV-13", "央视新闻": "CCTV-13",
    "CCTV-13新闻": "CCTV-13",
    "CCTV14": "CCTV-14", "少儿频道": "CCTV-14", "CCTV-14少儿": "CCTV-14",
    "CCTV15": "CCTV-15", "音乐频道": "CCTV-15", "CCTV-15音乐": "CCTV-15",
    "CCTV16": "CCTV-16", "奥林匹克": "CCTV-16", "CCTV16奥林匹克": "CCTV-16",
    "CCTV17": "CCTV-17", "农业农村": "CCTV-17", "CCTV-17农业农村": "CCTV-17",
    "CCTV4K": "CCTV-4K", "CCTV-4K超高清": "CCTV-4K", "央视4K": "CCTV-4K",
    "CGTN": "CGTN", "中国国际电视台": "CGTN", "CCTVNEWS": "CGTN",
    # ---- 卫视 ----
    "湖南电视台": "湖南卫视", "芒果台": "湖南卫视", "HUNANTV": "湖南卫视",
    "湖南卫视高清": "湖南卫视",
    "浙江电视台": "浙江卫视", "江苏电视台": "江苏卫视", "东方电视台": "东方卫视",
    "上海卫视": "东方卫视", "上海东方卫视": "东方卫视",
    "北京电视台": "北京卫视", "深圳电视台": "深圳卫视", "广东电视台": "广东卫视",
    "安徽电视台": "安徽卫视", "山东电视台": "山东卫视", "四川电视台": "四川卫视",
    "湖北电视台": "湖北卫视", "河南电视台": "河南卫视", "黑龙江电视台": "黑龙江卫视",
    "吉林电视台": "吉林卫视", "辽宁电视台": "辽宁卫视", "天津电视台": "天津卫视",
    "重庆电视台": "重庆卫视", "贵州电视台": "贵州卫视", "云南电视台": "云南卫视",
    "广西电视台": "广西卫视", "江西电视台": "江西卫视", "陕西电视台": "陕西卫视",
    "甘肃电视台": "甘肃卫视", "宁夏电视台": "宁夏卫视", "青海电视台": "青海卫视",
    "内蒙古电视台": "内蒙古卫视", "新疆电视台": "新疆卫视", "西藏电视台": "西藏卫视",
    "海南电视台": "海南卫视", "河北电视台": "河北卫视", "山西电视台": "山西卫视",
    "福建东南": "东南卫视", "福建卫视": "东南卫视", "东南电视台": "东南卫视",
    "厦门卫视": "厦门卫视", "延边卫视": "延边卫视", "兵团卫视": "兵团卫视",
    "大湾区卫视": "大湾区卫视", "澳亚卫视": "澳亚卫视",
    # ---- 港澳台 ----
    "凤凰卫视中文台": "凤凰卫视", "凤凰中文": "凤凰卫视",
    "凤凰资讯台": "凤凰卫视资讯台", "凤凰香港台": "凤凰卫视香港台",
    "翡翠台": "TVB翡翠台", "明珠台": "TVB明珠台", "无线翡翠台": "TVB翡翠台",
    "TVBS": "TVBS新闻", "TVBSNEWS": "TVBS新闻", "无线新闻台": "TVB无线新闻",
    "中天": "中天新闻", "东森": "东森新闻", "三立": "三立新闻",
}


def load_aliases(path: str = "data/aliases.json") -> dict[str, str]:
    """
    加载别名表：内置表 + 外部 JSON 覆盖。

    @param path  aliases.json 路径
    @retval      合并后的别名映射
    """
    merged = dict(BUILTIN_ALIASES)
    p = Path(path)
    if p.exists():
        try:
            ext = json.loads(p.read_text("utf-8"))
            merged.update({strip_noise(k): v for k, v in ext.items()})
        except Exception:
            pass
    return merged


_ALIASES = load_aliases()

_CCTV_RE = re.compile(r'^(?:CCTV|央视|中央)[-_]?(\d{1,2})(\+)?(?:台|频道)?$', re.I)


def canonical(name: str) -> str:
    """
    返回规范频道名，用于去重与展示。

    @param name  原始频道名
    @retval      规范名，无法识别时返回清洗后的原名
    """
    n = strip_noise(name)
    if not n:
        return "未知频道"
    if n in _ALIASES:
        return _ALIASES[n]

    m = _CCTV_RE.match(n)
    if m:
        return f"CCTV-{int(m.group(1))}{'+' if m.group(2) else ''}"

    # 湖南电视台 -> 湖南卫视
    if n.endswith("电视台"):
        return n[: -len("电视台")] + "卫视"
    return n


# ---------------------------------------------------------------- 去重
def dedupe(channels, max_per_channel: int = 8, max_per_host: int = 2):
    """
    同频道多 URL 保留策略。

    1) 按规范名分组
    2) 组内按 (来源权重降序, 延迟升序) 排序
    3) 每频道最多 max_per_channel 条，且同域名不超过 max_per_host 条

    @param channels         Channel 列表
    @param max_per_channel  每频道最多保留数
    @param max_per_host     同域名最多保留数
    @retval                去重后的 Channel 列表
    """
    import urllib.parse as up

    groups: dict[str, list] = {}
    for c in channels:
        c.name = canonical(c.name)
        if c.name == "未知频道" or not c.url:
            continue
        groups.setdefault(c.name, []).append(c)

    result = []
    for _name, lst in groups.items():
        def sort_key(c):
            host = up.urlparse(c.url).netloc
            lat = c.latency_ms if c.latency_ms >= 0 else 99_999
            return (-c.weight, lat, host)

        lst.sort(key=sort_key)
        seen_host: dict[str, int] = {}
        kept = 0
        for c in lst:
            host = up.urlparse(c.url).netloc
            if seen_host.get(host, 0) >= max_per_host:
                continue
            seen_host[host] = seen_host.get(host, 0) + 1
            result.append(c)
            kept += 1
            if kept >= max_per_channel:
                break
    return result
