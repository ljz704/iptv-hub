# -*- coding: utf-8 -*-
"""
点播源（TVBox sites）抓取、健康检查与合并。

背景：
    TVBox 配置分两半 ——
      lives  = 直播源（频道），本项目的 probe.py 负责
      sites  = 点播源（电视剧/电影，支持搜索），本模块负责

    点播源是「采集接口」，每条 site 形如：
      {"key":"csp_AppYs","name":"AppYs","type":3,
       "api":"cms_json_AppYs","searchable":1,"quickSearch":1,
       "filterable":1,"ext":"https://xxx.com/api.php/provide/vod/"}

    播放器通过这些 api 搜索剧名、拿剧集列表、再取播放地址。
    所以点播"能搜剧"是播放器的能力，前提是配置里得有 sites 数组。

本模块做的事：
    1. 从上游 TVBox 配置里抽取 sites
    2. 按域名做健康检查（HEAD/GET 探测 api 是否还活着）
    3. 去重合并，输出为标准 TVBox 配置
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse as up
from pathlib import Path

import aiohttp

from .config import CONFIG

log = logging.getLogger("sites")

# 点播源类型：1=xml, 3=cms(苹果CMS/json), 4=spider(JAR), 0=嗅探
# 这里只保留纯 HTTP 采集接口（type 1/3），JAR 类型需配套 spider 包，跨配置不通用
KEEP_TYPES = {1, 3}


def _as_str(v) -> str:
    """
    把任意类型的字段安全转为字符串。

    实测 TVBox 配置里 ext / api 字段并不总是字符串 ——
    可能是 dict（多接口）、list，甚至数字，直接 .startswith 会崩。

    @param v  原始值
    @retval   字符串形式
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        # 多接口字典：取第一个 http 值
        for val in v.values():
            s = _as_str(val)
            if s.startswith("http"):
                return s
        return ""
    if isinstance(v, (list, tuple)):
        for val in v:
            s = _as_str(val)
            if s.startswith("http"):
                return s
        return ""
    return str(v).strip()


def extract_spider(text: str, base_url: str = "") -> str:
    """
    从 TVBox 配置中抽取 spider 解析器包的绝对地址。

    spider 字段格式形如 "./jar/fan.txt;md5;6c4ab..."，
    分号后是 md5 校验值，需剥离并把相对路径展开为绝对地址。

    @param text      JSON 正文
    @param base_url  配置自身的地址
    @retval          spider 绝对地址，没有则返回 ""
    """
    try:
        data = json.loads(text)
    except Exception:
        return ""

    raw = _as_str(data.get("spider"))
    if not raw:
        return ""

    # 剥离 ";md5;xxx" 校验后缀
    path = raw.split(";")[0].strip()
    if not path:
        return ""

    if path.startswith(("http://", "https://")):
        return path
    if not base_url:
        return ""
    return up.urljoin(base_url, path)


def extract_sites(text: str, source: str = "") -> list[dict]:
    """
    从 TVBox 配置 JSON 中抽取 sites 数组。

    @param text    JSON 正文
    @param source  来源上游名
    @retval        site 字典列表（已附 _source 字段）
    """
    try:
        data = json.loads(text)
    except Exception as exc:
        log.warning("解析 sites 失败 (%s): %s", source, exc)
        return []

    sites = data.get("sites") or []
    out = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        api = _as_str(s.get("api"))
        if not api:
            continue
        # 只保留能从 HTTP 直接访问的采集接口
        if not api.startswith(("http://", "https://", "csp_", "cms_")):
            continue
        try:
            stype = int(s.get("type", 3))
        except Exception:
            stype = 3
        if stype not in KEEP_TYPES:
            continue

        out.append({
            "key": _as_str(s.get("key")),
            "name": _as_str(s.get("name")),
            "type": stype,
            "api": api,
            "searchable": int(s.get("searchable", 1) or 0),
            "quickSearch": int(s.get("quickSearch", 1) or 0),
            "filterable": int(s.get("filterable", 1) or 0),
            "ext": _as_str(s.get("ext")),
            "_source": source,
        })

    log.info("上游 %s 抽取到 %d 个点播源", source, len(out))
    return out


def _api_probe_url(site: dict) -> str:
    """
    构造点播源的健康检查 URL。

    苹果CMS 标准接口：{ext}?ac=videolist&wd=测试
    没有 ext 的用 spider 包，无法直接探测，返回空串。

    @param site  site 字典
    @retval      探测地址，无法探测返回 ""
    """
    ext = _as_str(site.get("ext"))
    if not ext.startswith("http"):
        return ""

    base = ext.rstrip("/") + "/"
    # 标准苹果CMS采集接口的搜索请求
    return base + "?ac=videolist&wd=" + up.quote("测试")


def dedupe_sites(sites: list[dict]) -> list[dict]:
    """
    按 (name, 域名) 去重，同名保留优先搜索的。

    @param sites  site 列表
    @retval       去重后的列表
    """
    seen: set[tuple] = set()
    out = []
    for s in sites:
        host = ""
        ext = _as_str(s.get("ext"))
        if ext.startswith("http"):
            host = up.urlparse(ext).netloc.lower()
        key = (_as_str(s.get("name")).lower(), host)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


async def _probe_site(session: aiohttp.ClientSession, site: dict,
                      sem: asyncio.Semaphore) -> tuple[dict, bool, str]:
    """
    检查单个点播源是否可用。

    @param session  aiohttp 会话
    @param site     site 字典
    @param sem      并发信号量
    @retval         (site, 是否可用, 说明)
    """
    url = _api_probe_url(site)
    if not url:
        # 无 ext 的通常是需要本地下发 spider 包的源，跳过检查直接保留
        return site, True, "no-ext"

    async with sem:
        try:
            to = aiohttp.ClientTimeout(connect=5, total=10)
            async with session.get(url, timeout=to, ssl=False,
                                   allow_redirects=True) as r:
                if r.status >= 400:
                    return site, False, f"HTTP {r.status}"
                body = await r.content.read(4096)
                low = body[:512].lower()
                # 苹果CMS 正常返回 JSON，含 "list" 或 "class"
                if b'"list"' in body or b'"class"' in body or b"vod_" in low:
                    return site, True, "cms-ok"
                # 有内容但格式不像 CMS，可能是别的接口
                if len(body) > 100 and b"<html" not in low:
                    return site, True, "maybe"
                return site, False, "empty-or-html"
        except Exception as exc:
            return site, False, type(exc).__name__


async def probe_sites(sites: list[dict], concurrency: int = 40) -> list[dict]:
    """
    并发探测所有点播源，返回可用列表。

    @param sites        site 列表
    @param concurrency  并发数
    @retval             可用的 site 列表（含 _probe 字段说明）
    """
    if not sites:
        return []

    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     headers=CONFIG["headers"]) as s:
        results = await asyncio.gather(
            *(_probe_site(s, site, sem) for site in sites))

    alive = []
    for site, ok, note in results:
        site["_probe"] = note
        if ok:
            alive.append(site)

    log.info("点播源探测：%d/%d 可用", len(alive), len(sites))
    return alive


def write_tvbox_full(lives_path: str, sites: list[dict], path: str,
                     spider: str = "") -> None:
    """
    输出完整 TVBox 配置（含 lives 与 sites）。

    @param lives_path  直播 m3u 的相对路径
    @param sites       点播源列表
    @param path        输出路径
    @param spider      spider 包地址（可选）
    """
    cfg = {
        "lives": [
            {
                "name": "聚合直播",
                "type": 0,
                "url": lives_path,
                "playerType": 1,
            }
        ],
        "sites": [],
    }
    if spider:
        cfg["spider"] = spider

    for s in sites:
        item = {
            "key": s.get("key") or s.get("name", "")[:16],
            "name": s.get("name", ""),
            "type": s.get("type", 3),
            "api": s.get("api", ""),
            "searchable": s.get("searchable", 1),
            "quickSearch": s.get("quickSearch", 1),
            "filterable": s.get("filterable", 1),
        }
        if s.get("ext"):
            item["ext"] = s["ext"]
        cfg["sites"].append(item)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    log.info("已写出 %s（%d 个直播源组 + %d 个点播源）",
             path, len(cfg["lives"]), len(cfg["sites"]))
