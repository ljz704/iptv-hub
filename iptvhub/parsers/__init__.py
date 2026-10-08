# -*- coding: utf-8 -*-
"""解析器注册表。"""
from .base import Channel
from .m3u import parse as parse_m3u
from .plain_txt import parse as parse_txt
from .tvbox import parse_lives, parse_multi, resolve_deferred

PARSERS = {
    "m3u": parse_m3u,
    "txt": parse_txt,
    "tvbox": parse_lives,
}

__all__ = [
    "Channel", "parse_m3u", "parse_txt", "parse_lives",
    "parse_multi", "resolve_deferred", "PARSERS",
]
