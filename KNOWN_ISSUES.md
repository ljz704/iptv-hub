# 踩坑记录 —— IPTV 源聚合

## 1. 移动运营商源（chinamobile.com）在本环境下不可用

**现象**：所有 `ottrrs.*.chinamobile.com`、`223.110.x.x`、`183.207.x.x` 源返回
`HTTP 502 Bad Gateway`，响应体为空，连 `Server` 响应头都没有。

**排查过程**：
- 确认出口 IP `120.240.178.162` 归属 **中国移动 AS9808**（用了 ip-api.com 交叉验证）
- 确认域名可解析：`ottrrs.hl.chinamobile.com` → `39.134.65.106`（移动 IP 段）
- 测试 6 种请求头组合（浏览器 UA / 机顶盒 UA / okhttp / 带 Referer / 移动视频 UA）
  **全部 502**
- 对照组：浙江广电 `l.cztvcloud.com`、吉林广电 `stream2.jlntv.cn` 均 HTTP 200 正常

**结论**：不是鉴权问题，是移动网关在该网络出口不接受请求。
移动 OTT 源需要 **IPTV 专用通道**（VLAN 或组播），普通宽带上网出口访问不了。

**应对**：聚合时把移动源一并探测，不通就自然剔除，不要手工加白名单。

---

## 2. 央视网（cctv.com）官方源无法做成静态 m3u

**现象**：历代流传的央视网 CDN 域名全部失效。

| 域名 | 状态 |
|---|---|
| `cctvcnch5c.v.wscdns.com` | DNS 解析失败 |
| `cctvcnch5c.v.cntv.cn` | DNS 解析失败 |
| `live.cntv.cn` / `cctv1.live.cntv.cn` | DNS 解析失败 |
| `vdn.apps.cntv.cn` | 可解析，但接口返回 `{"errcode":"1002","msg":"data empty"}` |
| `tv.cctv.com` | 页面通，但为 JS 渲染，HTML 里**没有任何 m3u8 地址** |

**根因**：央视网直播流带**动态签名 token**，有效期约 30 分钟。
页面加载后由 JS 异步请求接口获取带 token 的地址。

**佐证**：检查了 3 个活跃维护的 TVBox 配置（86 / 135 / 51 个 sites），
**央视相关条目均为 0 条** —— 整个生态都不用央视网官方源，因为静态配置装不下动态 token。

**应对**：央视台用「央视频」官方 App；聚合源里的 CCTV 走转播源（运营商/地方广电）。

---

## 3. 深度验证能发现普通探测漏掉的假活源

**背景**：普通探测只看 HTTP 状态码 + 前 4KB 特征，会把
「播放列表返回 200 但分片已被删除」的源误判为可用。

**实测数据**（604 条频道）：

```
普通探测   存活 ~100%
深度验证   存活 77.5%
  ├─ 93 条  no-sync        非 TS 流的假源
  ├─ 33 条  seg HTTP 404   播放列表在，分片 404  ← 普通探测漏掉的
  ├─ 3 条   sub HTTP 404
  └─ 3 条   seg-too-small
```

**实现**：`iptvhub/probe.py` 的 `_verify_hls_segment()`，
用法 `python -m iptvhub.cli --deep`。

---

## 4. 上游 URL 必须实测，不能凭猜测写

**踩过的坑**：

| 猜测的路径 | 实际结果 |
|---|---|
| `iptv-org/iptv/master/index.m3u` | 404 |
| `iptv-org/iptv/master/streams/cn_sichuan.m3u` | 404 |
| `iptv-org/iptv/master/streams/cn_hk.m3u` | 404（正确名是 `hk.m3u`） |
| `best-fan/iptv-sources/main/tv.m3u` | 404 |
| `jiandantv/IPTV2025/main/iptv.m3u` | 404 |

**实测有效的路径**：

| 源 | 规模 |
|---|---|
| `imDazui/Tvlist-awesome-m3u-m3u8/master/m3u/china.m3u` | 1004 频道 |
| `vbskycn/iptv/master/tv/iptv4.m3u` | 544 频道 |
| `iptv-org/iptv/master/streams/cn.m3u` | 508 频道 |
| `YueChan/Live/main/IPTV.m3u` | 96 频道 |

**规范**：新增上游前先 `curl -I` 验证，别写进配置再发现 404。

---

## 5. GitHub 镜像在不同场景表现相反

**大文件下载**（150MB APK）：

| 镜像 | 速度 |
|---|---|
| `ghfast.top` | 1620 KB/s |
| `gh-proxy.com` | 198 KB/s |
| `ghproxy.net` | 11 KB/s |
| `github.com` 直连 | 超时 |

**小文件请求**（577KB spider 包，3 次重试）：

| 镜像 | 成功率 | 耗时 |
|---|---|---|
| `gh-proxy.com` | 3/3 | 0.6~1.5s |
| `ghproxy.net` | 3/3 | 1.7~3.4s |
| `ghfast.top` | 2/3 | 4.3s（偶发 SSL 握手超时） |

**结论**：下载大文件用 `ghfast.top`，配置/API 类小文件用 `gh-proxy.com`。

---

## 6. TVBox 配置里 ext 字段类型不定

**现象**：解析 sites 时 `AttributeError: 'dict' object has no attribute 'startswith'`。

**原因**：TVBox 配置的 `ext` / `api` 字段不一定是字符串，
可能是 dict（多接口）、list 甚至数字。

**修复**：`iptvhub/sites.py` 的 `_as_str()` 统一做类型防御。
