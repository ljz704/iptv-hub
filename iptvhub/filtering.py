# -*- coding: utf-8 -*-
"""
频道/源合法性过滤。

背景（实测数据）：
    聚合 167,775 条后，97% 的条目来自单一域名 em.21dtv.com，
    且 86% 的名字是「歌手-歌名」形态（卫兰-就算世界无童话、陈奕迅-富士山下）。
    真正的电视频道只有约 1,846 条（含频道关键词的比例仅 1.2%）。

结论：单靠名字过滤不足以去掉噪声，必须叠加**源级域名黑名单**——
     一个域名贡献了超过阈值比例的条目且几乎没有频道特征词时，
     整个域名判定为点播/音乐源并剔除。
"""
from __future__ import annotations

import collections
import re
import urllib.parse as up

# ---------------------------------------------------------------- 名字层
TV_KEYWORDS = re.compile(
    r'(CCTV|央视|卫视|电视台|频道|广播|台$|综合|新闻|影视|剧场|体育|少儿|'
    r'卡通|纪录|纪实|音乐|戏曲|财经|法制|农业|军事|电影|电视剧|生活|公共|'
    r'都市|科教|HD|高清|CGTN|国际|海外|'
    r'TVB|翡翠|明珠|凤凰|澳视|中天|东森|三立|民视|台视|华视|中视|无线|'
    r'news|sports|movie|kids|discovery|national|geographic)',
    re.I)

# 明确的点播/垃圾特征
JUNK_PATTERNS = re.compile(
    r'(第\d+集|第\d+季|EP\d+|S\d{2}E\d{2}|'
    r'演唱会|音乐视频|油管|YouTube|抖音|快手|哔哩|'
    r'\.(mp4|mkv|avi|flv|rmvb|wmv|mov)$)',
    re.I)

MAX_NAME_LEN = 30

# ---------------------------------------------------------------- 电台识别
# 实测：二级订阅里有大量广播电台（收音机），占总量 44%：
#   海南旅游广播、温州私家车音乐广播FM100.3、CNR文艺之声、KFM981
# 电视端播放器不需要这些，默认剔除。
RADIO_RE = re.compile(
    r'(广播|电台|频率|调频|之声|FREQUENCY|RADIO|'
    r'FM\s?\d|AM\s?\d|新闻台|交通台|音乐台|经济台|文艺台|'
    r'CNR|CRI|KFM|CITYFM|CAPITALFM)',
    re.I)

# 但某些含"广播"字样的确实是电视频道，白名单优先
RADIO_EXEMPT_RE = re.compile(
    r'(电视台|卫视|CCTV|广播电视台|TV)',
    re.I)

# ---------------------------------------------------------------- 点播分组
# 分组名本身即点播/音乐类的，整组剔除。
# 实测 group-title="16万•MV" 下的条目 100% 是音乐视频而非直播频道。
VOD_GROUP_RE = re.compile(
    r'(MV|音乐视频|歌曲|点播|网盘|影视点播|曲库|歌单|舞曲|DJ|'
    r'演唱会|KTV|相声小品|短视频|油管|YouTube|抖音|影视$|电影$)',
    re.I)

# 要整组剔除的分组（实测：这些不是电视频道）
#   直播中国    = 风景摄像头直播，共 76 条
#   数字/数字频道 = 无意义编号占位
#   电台类      = 广播电台（初秋语•电台 / 范明明•电台），共 72 条
DROP_GROUP_RE = re.compile(
    r'(电台|直播中国|数字频道|^数字$)',
    re.I)

# 上游分组名不规范，归一到标准分组
GROUP_NORMALIZE = {
    '卫视频道': '卫视',
    '央视频道': '央视',
    '地方频道': '地方',
    '电影频道': '影视',
    '纪录频道': '纪录',
    '儿童频道': '少儿',
    '解说频道': '体育',
    '春晚频道': '其他',
    '数字频道': '其他',
}

# ---------------------------------------------------------------- 形态层
_DASH = re.compile(r'[-－—]')


def looks_like_song(name: str) -> bool:
    """
    判断名字是否像「歌手-歌名」。

    规则：恰好一个连字符，两侧各 1~12 字符，且不含频道特征词。

    @param name  频道名
    @retval      True 表示疑似歌曲
    """
    if TV_KEYWORDS.search(name):
        return False
    parts = _DASH.split(name)
    if len(parts) != 2:
        return False
    return all(1 <= len(p.strip()) <= 12 for p in parts)


def is_radio(name: str) -> bool:
    """
    判断是否广播电台（非电视）。

    @param name  频道名
    @retval      True 表示是电台
    """
    if RADIO_EXEMPT_RE.search(name):
        return False
    return bool(RADIO_RE.search(name))


# 畸形名：CCTV- 后跟 3 位以上数字（如 CCTV-10576I），或纯数字编号
MALFORMED_RE = re.compile(r'^CCTV-\d{3,}|^\d{4,}$', re.I)


def is_likely_channel(name: str) -> bool:
    """
    名字层判断：是否像电视频道。

    @param name  清洗后的频道名
    @retval      True 表示保留
    """
    if not name:
        return False
    n = name.strip()
    if len(n) < 2 or len(n) > MAX_NAME_LEN:
        return False
    if JUNK_PATTERNS.search(n):
        return False
    if MALFORMED_RE.match(n):
        return False
    return True


# ---------------------------------------------------------------- 源层
def audit_hosts(channels: list, min_count: int = 30,
                kw_ratio_floor: float = 0.02) -> tuple[dict, set]:
    """
    统计各域名的条目数与频道特征词命中率，判定黑名单域名。

    判定依据（实测驱动）：
      一个域名条目量大但几乎没有频道特征词时，它是点播/音乐/网盘类内容源，整域剔除。
      实测样本：
        em.21dtv.com             162384 条  kw=0.011  song=0.915  -> 音乐站
        vodcdn.video.taobao.com     124 条  kw=0.000  song=1.000  -> 点播
        vd2.bdstatic.com            224 条  kw=0.004  song=0.009  -> 百度网盘 CDN
      后者的歌曲率很低，只靠 song_ratio 判不出来，所以主判据用 kw_ratio。

    @param channels       Channel 列表
    @param min_count      参与判定的最小条目数
    @param kw_ratio_floor 特征词命中率下限，低于此值且量大则拉黑
    @retval               (统计字典, 黑名单域名集合)
    """
    by_host: dict[str, list] = collections.defaultdict(list)
    for c in channels:
        host = up.urlparse(c.url).netloc.lower()
        if host:
            by_host[host].append(c)

    stats: dict[str, dict] = {}
    blacklist: set[str] = set()

    for host, items in by_host.items():
        kw_hits = sum(1 for c in items if TV_KEYWORDS.search(c.name))
        song_hits = sum(1 for c in items if looks_like_song(c.name))
        kw_ratio = kw_hits / len(items)
        song_ratio = song_hits / len(items)

        blocked = False
        if len(items) >= min_count:
            # 主判据：量大 + 频道特征词极少 -> 点播/音乐/网盘源
            if kw_ratio < kw_ratio_floor:
                blocked = True
            # 辅助判据：歌曲形态占多数
            elif song_ratio > 0.5:
                blocked = True

        stats[host] = {
            "count": len(items),
            "kw_ratio": round(kw_ratio, 4),
            "song_ratio": round(song_ratio, 4),
            "blocked": blocked,
        }
        if blocked:
            blacklist.add(host)

    return stats, blacklist


def match_blacklist(host: str, blacklist: set[str]) -> bool:
    """
    判断域名是否命中黑名单（支持子域名后缀匹配）。

    实测：16万•MV 会更换 CDN 域名，vd2/vd3/vd4.bdstatic.com 需一并拦截，
    因此黑名单按后缀匹配 —— 登记 bdstatic.com 即可覆盖所有子域。

    @param host       待检查域名
    @param blacklist  黑名单条目集合
    @retval           True 表示命中
    """
    if not host:
        return False
    h = host.lower().split(':')[0]
    for b in blacklist:
        if h == b or h.endswith('.' + b):
            return True
    return False


def filter_channels(channels: list,
                    use_host_blacklist: bool = True,
                    drop_radio: bool = True) -> tuple[list, dict]:
    """
    三级过滤：源级域名黑名单 + 电台剔除 + 名字层合法性。

    @param channels            Channel 列表
    @param use_host_blacklist  是否启用域名黑名单
    @param drop_radio          是否剔除广播电台（电视端默认剔除）
    @retval                    (过滤后的列表, 审计信息)
    """
    from .config import HOST_BLACKLIST_EXTRA

    audit: dict = {}

    # --- 第 1 级：手工黑名单（后缀匹配）---
    manual_hit = [c for c in channels
                  if match_blacklist(up.urlparse(c.url).netloc,
                                     set(HOST_BLACKLIST_EXTRA))]
    if manual_hit:
        hits = {up.urlparse(c.url).netloc.lower() for c in manual_hit}
        audit["manual_blocked_hosts"] = sorted(hits)
        before = len(channels)
        channels = [c for c in channels
                    if not match_blacklist(up.urlparse(c.url).netloc,
                                           set(HOST_BLACKLIST_EXTRA))]
        audit["manual_blocked_count"] = before - len(channels)

    # --- 第 2 级：自动审计黑名单 ---
    if use_host_blacklist:
        host_stats, blacklist = audit_hosts(channels)
        audit["blacklist"] = sorted(blacklist)
        audit["host_stats"] = host_stats
        if blacklist:
            before = len(channels)
            channels = [c for c in channels
                        if not match_blacklist(up.urlparse(c.url).netloc,
                                               blacklist)]
            audit["blocked_count"] = before - len(channels)

    # --- 第 3 级：点播分组剔除（按 group-title 整组拦）---
    before = len(channels)
    channels = [c for c in channels
                if not (c.group and VOD_GROUP_RE.search(c.group))]
    audit["dropped_vod_group"] = before - len(channels)

    # --- 第 3.5 级：非电视频道分组剔除（电台/风景直播/数字占位）---
    before = len(channels)
    channels = [c for c in channels
                if not (c.group and DROP_GROUP_RE.search(c.group))]
    audit["dropped_group"] = before - len(channels)

    # --- 第 3.6 级：分组名规范化 ---
    renamed = 0
    for c in channels:
        if c.group in GROUP_NORMALIZE:
            c.group = GROUP_NORMALIZE[c.group]
            renamed += 1
    audit["group_renamed"] = renamed

    # --- 第 4 级：电台剔除 ---
    if drop_radio:
        before = len(channels)
        channels = [c for c in channels if not is_radio(c.name)]
        audit["dropped_radio"] = before - len(channels)

    # --- 第 5 级：名字合法性 ---
    before = len(channels)
    channels = [c for c in channels if is_likely_channel(c.name)]
    audit["dropped_by_name"] = before - len(channels)

    return channels, audit
