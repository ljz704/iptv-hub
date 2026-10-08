# -*- coding: utf-8 -*-
"""
IPTV Hub 主流程入口。

流水线：
    抓取上游 -> 解析 -> 展开 deferred -> 归一化去重 -> 并发探测
    -> 再按探测结果排序保留 -> 输出 m3u / 多源 m3u / txt / tvbox json

用法：
    python -m iptvhub.cli
    python -m iptvhub.cli --no-probe        # 跳过探测（快速预览）
    python -m iptvhub.cli --out dist
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .classify import classify
from .config import CONFIG, UPSTREAMS
from .fetcher import fetch_all
from .filtering import filter_channels
from .normalize import dedupe
from .parsers import (PARSERS, Channel, parse_lives, parse_multi,
                      resolve_deferred)
from .probe import probe_all
from .quality import append_history, build_stats, check_alerts, notify
from .sites import (dedupe_sites, extract_sites, extract_spider,
                    probe_sites, write_tvbox_full)
from .writers import (write_m3u, write_multi_m3u, write_stats,
                      write_txt, write_tvbox)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cli")


async def run(out_dir: str = "dist", do_probe: bool = True) -> int:
    """
    执行完整聚合流水线。

    @param out_dir   输出目录
    @param do_probe  是否做健康探测
    @retval          退出码，0 正常，1 告警
    """
    # ---- 1. 抓取 ----
    log.info("开始抓取上游…")
    raw_map = await fetch_all()
    if not raw_map:
        log.error("全部上游抓取失败，终止")
        return 1

    # ---- 2. 解析 ----
    up_by_name = {u.name: u for u in UPSTREAMS}
    channels: list[Channel] = []
    per_upstream: dict[str, dict] = {}
    all_sites: list[dict] = []          # 点播源（sites）
    spider_url = ""                     # 解析器包地址

    for name, (text, base_url) in raw_map.items():
        up = up_by_name.get(name)
        if not up:
            continue

        # 顺手抽取点播源（sites 数组）与 spider 包，供搜剧使用
        if up.kind in ("tvbox", "tvbox_multi"):
            all_sites.extend(extract_sites(text, name))
            if not spider_url:
                spider_url = extract_spider(text, base_url)

        if up.kind == "tvbox_multi":
            # 多仓入口：先展开 urls 数组，再把每个子仓当作单仓处理
            subs = parse_multi(text)
            log.info("多仓 %s 展开出 %d 个子仓", name, len(subs))
            for sub in subs:
                channels.append(Channel(name=f"__DEFERRED__{sub['name']}",
                                        url=sub["url"], group=sub["name"],
                                        source=name, weight=up.weight))
        elif up.kind == "tvbox":
            # 单仓：解析 lives，相对路径按 base_url 展开
            got = parse_lives(text, name, up.weight, base_url)
            log.info("上游 %s 解析出 %d 条（含二级订阅）", name, len(got))
            channels.extend(got)
        else:
            parser = PARSERS.get(up.kind)
            if not parser:
                log.warning("未知上游类型 %s", up.kind)
                continue
            got = parser(text, name, up.weight)
            log.info("上游 %s 解析出 %d 条", name, len(got))
            channels.extend(got)

        per_upstream[name] = {"raw": len(channels)}

    # ---- 3. 展开 deferred（TVBox 二次拉取）----
    deferred_n = sum(1 for c in channels if c.name.startswith("__DEFERRED__"))
    if deferred_n:
        log.info("展开 %d 个二级订阅…", deferred_n)
        channels = await resolve_deferred(channels)

    if not channels:
        log.error("解析后无任何频道")
        return 1

    # 按上游统计原始条数
    raw_counts: dict[str, int] = {}
    for c in channels:
        if c.source:
            raw_counts[c.source] = raw_counts.get(c.source, 0) + 1
    for name, n in raw_counts.items():
        per_upstream.setdefault(name, {})["parsed"] = n

    log.info("解析总计 %d 条", len(channels))

    # ---- 3.5 四级过滤 ----
    before_filter = len(channels)
    channels, audit = filter_channels(channels)

    mb = audit.get("manual_blocked_count", 0)
    if mb:
        log.info("手工黑名单命中 %d 条，域名: %s",
                 mb, ", ".join(audit.get("manual_blocked_hosts", [])[:6]))

    blocked = audit.get("blocked_count", 0)
    if audit.get("blacklist"):
        log.info("自动审计拉黑 %d 个域名: %s",
                 len(audit["blacklist"]), ", ".join(audit["blacklist"][:8]))

    dropped_radio = audit.get("dropped_radio", 0)
    dropped_name = audit.get("dropped_by_name", 0)
    dropped_vod = audit.get("dropped_vod_group", 0)

    log.info("过滤：黑名单 %d ｜ 点播组 %d ｜ 电台 %d ｜ 脏名 %d ｜ 共 %d -> %d",
             mb + blocked, dropped_vod, dropped_radio, dropped_name,
             before_filter, len(channels))

    # 输出审计文件供排查
    if audit.get("host_stats"):
        top = sorted(audit["host_stats"].items(),
                     key=lambda kv: -kv[1]["count"])[:50]
        audit_out = {
            "blacklist": audit["blacklist"],
            "top_hosts": [
                {"host": h, **s} for h, s in top
            ],
        }
        write_stats(audit_out, f"{out_dir}/audit_hosts.json")

    # ---- 4. 归一化 + 去重 ----
    deduped = dedupe(channels,
                     max_per_channel=CONFIG["quality"].max_per_channel,
                     max_per_host=CONFIG["quality"].max_per_host)
    log.info("去重后 %d 条（%d 个唯一频道）",
             len(deduped), len({c.name for c in deduped}))

    # ---- 5. 探测 ----
    pre_probe = len(deduped)
    if do_probe:
        deduped = await probe_all(deduped)
    else:
        log.info("跳过探测（--no-probe）")

    # 按上游统计存活条数
    alive_counts: dict[str, int] = {}
    for c in deduped:
        if c.source:
            alive_counts[c.source] = alive_counts.get(c.source, 0) + 1
    for name in per_upstream:
        per_upstream[name]["alive"] = alive_counts.get(name, 0)
        per_upstream[name].setdefault("raw", 0)
        per_upstream[name]["parsed"] = per_upstream[name].get("parsed", 0)

    if not deduped:
        log.error("探测后无存活源")
        chans = []
    else:
        # 按分组 + 延迟重排，让最好的源排前面
        deduped.sort(key=lambda c: (
            classify(c.name, c.group),
            -(c.weight),
            c.latency_ms if c.latency_ms >= 0 else 99_999,
        ))
        chans = deduped

    # ---- 6. 输出 ----
    write_m3u(chans, f"{out_dir}/live.m3u")
    write_multi_m3u(chans, f"{out_dir}/live_multi.m3u")
    write_txt(chans, f"{out_dir}/live.txt")

    # ---- 6.5 点播源：去重 + 探测 + 合并输出 ----
    if all_sites:
        all_sites = dedupe_sites(all_sites)
        log.info("点播源去重后 %d 个，开始探测…", len(all_sites))
        all_sites = await probe_sites(all_sites)

        # 按探测结果排序，可用的排前面
        all_sites.sort(key=lambda s: (
            0 if s.get("_probe") in ("cms-ok", "maybe") else 1,
            -int(s.get("searchable", 0)),
            s.get("name", "")))

        # spider 包地址需换成国内可达的镜像，否则电视端拉不到解析器
        spider_final = spider_url
        if spider_url and "raw.githubusercontent.com/" in spider_url:
            from .fetcher import mirror_candidates
            cands = mirror_candidates(spider_url)
            # 第一个候选即 ghproxy.net 代理（实测唯一可用）
            if len(cands) > 1:
                spider_final = cands[1]
                log.info("spider 换用镜像: %s", spider_final[:80])

        write_tvbox_full("./live.m3u", all_sites, f"{out_dir}/tvbox.json",
                         spider=spider_final)
        log.info("点播源可用 %d 个，已写入 tvbox.json", len(all_sites))
    else:
        write_tvbox(chans, f"{out_dir}/tvbox.json", "./live.m3u")
        log.warning("未抽取到点播源（sites 为空）")

    # ---- 7. 统计 + 告警 ----
    stats = build_stats(pre_probe, len(chans), per_upstream)
    stats["total_raw"] = len(channels)
    write_stats(stats, f"{out_dir}/stats.json")
    append_history(stats)

    alerts = check_alerts(stats)
    notify(alerts)

    log.info("完成：原始 %d -> 去重 %d -> 存活 %d（存活率 %.1f%%）",
             len(channels), pre_probe, len(chans),
             stats["alive_ratio"] * 100)
    return 1 if alerts else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="IPTV 源自动聚合")
    ap.add_argument("--out", default="dist", help="输出目录")
    ap.add_argument("--no-probe", action="store_true", help="跳过健康探测")
    args = ap.parse_args()

    code = asyncio.run(run(args.out, not args.no_probe))
    sys.exit(code)


if __name__ == "__main__":
    main()
