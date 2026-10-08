# -*- coding: utf-8 -*-
"""解析器公共数据模型。"""
from dataclasses import dataclass, field


@dataclass
class Channel:
    """
    一条频道记录。

    @param name      原始频道名（归一化前）
    @param url       播放地址
    @param group     分组名
    @param tvg_id    EPG 标识
    @param tvg_logo  台标地址
    @param source    来源上游名
    @param weight    来源权重
    @param latency_ms 探测延迟，-1 未探测，-2 组播，-3 内网
    """
    name: str
    url: str
    group: str = "未分组"
    tvg_id: str = ""
    tvg_logo: str = ""
    source: str = ""
    weight: float = 1.0
    latency_ms: int = -1

    def key(self) -> tuple[str, str]:
        """唯一键：频道名 + url。"""
        return (self.name, self.url)
