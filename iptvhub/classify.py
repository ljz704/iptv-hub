# -*- coding: utf-8 -*-
"""分组归类：优先按规范名关键词匹配，其次沿用上游分组。"""
from __future__ import annotations

import re

RULES: list[tuple[str, re.Pattern]] = [
    ("央视", re.compile(r'^CCTV-')),
    ("卫视", re.compile(r'卫视$')),
    ("港澳台", re.compile(r'(TVB|翡翠|明珠|凤凰|澳视|澳门|台湾|中天|东森|三立|民视|台视|华视|中视|无线)')),
    ("影视", re.compile(r'(电影|影视|剧场|美剧|韩剧|日剧|CHC|HBO|STAR|影院|CINEMA)')),
    ("体育", re.compile(r'(体育|足球|篮球|赛事|NBA|英超|中超|西甲|德甲|F1|电竞|GOLF|斯诺克)')),
    ("少儿", re.compile(r'(少儿|卡通|动漫|动画|KAKU|优漫|金鹰卡通|嘉佳|哈哈)')),
    ("新闻", re.compile(r'(新闻|资讯|NEWS|财经|经济|证券|CGTN)')),
    ("纪录", re.compile(r'(纪录|纪实|探索|地理|DISCOVERY|NGC|国家地理|BBC)')),
    ("音乐", re.compile(r'(音乐|MV|演唱会|戏曲|曲艺)')),
    ("地方", re.compile(r'(市台|县台|区台|省台|综合频道|公共频道|都市|生活|影视娱乐)')),
    ("国际", re.compile(r'(国际|海外|WORLD|GLOBAL|SKY|CNN|BBC|NHK|KBS)')),
]

GROUP_ORDER = ["央视", "卫视", "港澳台", "影视", "体育", "少儿",
               "新闻", "纪录", "音乐", "地方", "国际", "其他"]


def classify(name: str, upstream_group: str = "") -> str:
    """
    判定频道分组。

    @param name            规范频道名
    @param upstream_group  上游自带分组名（兜底）
    @retval                分组名
    """
    for group, pat in RULES:
        if pat.search(name):
            return group
    if upstream_group and upstream_group not in ("未分组", "其他"):
        return upstream_group
    return "其他"


def group_rank(group: str) -> int:
    """分组排序序号，未登记的排最后。"""
    return GROUP_ORDER.index(group) if group in GROUP_ORDER else len(GROUP_ORDER)
