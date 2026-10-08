# -*- coding: utf-8 -*-
"""
IPTV Hub 全局配置：上游清单、探测参数、质量阈值、镜像回退链。

REF: 上游源分层策略 —— 权重高的优先保留在去重结果前列
"""
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 网络
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# raw.githubusercontent.com 的镜像回退链，按顺序尝试。
# {p} 为 raw 之后的路径，例如 iptv-org/iptv/master/streams/cn.m3u
#
# 顺序依据 2025 实测（国内网络）：
#   ghproxy.net        OK ~3.9s   <- 主力
#   gitee 镜像          OK ~3.3s   <- 仅对已同步到 gitee 的仓库有效
#   jsdelivr           FAIL 超时   <- 保留但排后
#   gh-proxy.com       FAIL 超时
#   raw.githubusercontent.com FAIL 超时  <- 排最后，境外或有代理时可用
RAW_MIRRORS = [
    "https://ghproxy.net/https://raw.githubusercontent.com/{p}",
    "https://gh-proxy.com/https://raw.githubusercontent.com/{p}",
    "https://cdn.jsdelivr.net/gh/{p}",
    "https://raw.githubusercontent.com/{p}",
]


# ---------------------------------------------------------------- 上游
@dataclass
class Upstream:
    """单个上游源的描述。"""
    name: str
    url: str
    kind: str               # m3u | txt | tvbox | tvbox_multi
    weight: float = 1.0     # 去重排序权重，越大越优先
    enabled: bool = True


# 上游清单。URL 路径均已实测（2025），404 的已剔除。
# 备注：iptv-org 仓库的 index.m3u / streams/cn_sichuan.m3u 均返回 404，
#       有效路径只有 streams/*.m3u，新增上游前务必先 HEAD 验证。
UPSTREAMS: list[Upstream] = [
    Upstream("iptv-org-cn",
             "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
             "m3u", 1.0),
    Upstream("iptv-org-hk",
             "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/hk.m3u",
             "m3u", 0.7),
    Upstream("iptv-org-tw",
             "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/tw.m3u",
             "m3u", 0.6),
    Upstream("iptv-org-mo",
             "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/mo.m3u",
             "m3u", 0.5),
    Upstream("tvbox-gao",
             "https://raw.githubusercontent.com/gaotianliuyun/gao/master/0821.json",
             "tvbox", 0.9),
]


# ---------------------------------------------------------------- 过滤
# 上游二级订阅黑名单：整体禁用的 TVBox lives 条目名。
#
# 教训：16万•MV 这类音乐/点播站会不断更换 CDN 域名（实测从 bdstatic.com
# 换到 mvbox.cn、haiqu.vip、68tool.com、yximgs.com），追域名是打地鼠。
# 正确做法是在**源级别**整体禁用，因为它提供的本来就是点播内容而非直播。
SUB_FEED_BLACKLIST = [
    "16万•MV",
    "YuanHsing•油管",
]

# 域名黑名单（兜底）。按后缀匹配，登记 bdstatic.com 可覆盖 vd2/vd3/vd4 子域。
HOST_BLACKLIST_EXTRA = [
    "bdstatic.com",          # 百度网盘 CDN，点播内容
    "kwimgs.com",            # 快手 CDN
    "yximgs.com",            # 快手 CDN（另一域名）
    "kuwo.cn",               # 酷我音乐
    "21dtv.com",             # 音乐站
    "faiusr.com",            # 建站平台
    "taobao.com",            # 淘宝点播
    "alicdn.com",            # 阿里 CDN 点播
    "bilibili.com",          # B 站点播
    "douyin.com",            # 抖音
    "kuaishou.com",          # 快手
]


# ---------------------------------------------------------------- 探测
@dataclass
class ProbeConfig:
    """健康探测参数。"""
    concurrency: int = 200          # 全局并发协程数
    timeout_connect: float = 5.0    # 连接超时
    timeout_read: float = 8.0       # 总超时
    retries: int = 1                # 失败重试次数
    head_bytes: int = 4096          # 只读前 N 字节做特征判定
    min_bytes: int = 188 * 4        # 最少 4 个 TS 包
    max_latency_ms: int = 4000      # 超过此延迟降权，不剔除
    batch_per_host: int = 4         # 同域名并发上限，避免被 ban


# ---------------------------------------------------------------- 质量
@dataclass
class QualityConfig:
    """质量与告警阈值。"""
    min_alive_ratio: float = 0.35    # 总体存活率低于此值告警
    per_upstream_min: float = 0.10   # 单上游最低存活率
    max_per_channel: int = 8         # 每个频道最多保留的备用 url 数
    max_per_host: int = 2            # 同域名最多保留条数
    keep_days: int = 30              # 历史版本留存天数


CONFIG = {
    "probe": ProbeConfig(),
    "quality": QualityConfig(),
    "headers": {
        "User-Agent": UA,
        "Accept": "*/*",
        "Connection": "close",
    },
}
