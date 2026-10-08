# IPTV Hub —— 免费电视源自动聚合 + 手机远程换源

给 TCL 安卓电视用的开源方案：**自动抓取免费直播源 → 健康探测 → 输出订阅文件 → 电视端播放 → 手机远程换源**。

源失效了不用管，定时任务自己换；想手动干预，手机连同一 WiFi 打开浏览器就能操作。

---

## 它解决什么问题

免费直播源有三个坑：

1. **来源散** —— 散落在几十个 GitHub 仓库、TVBox 接口、社区帖子里
2. **死得快** —— 实测 2630 条源里只有 1444 条能播，**存活率 54.9%**
3. **手动改麻烦** —— 电视上改订阅地址要拿遥控器戳半天

本方案把这三件事自动化：聚合去重 → 探测剔除死源 → 定时发布 → 手机端随时换。

---

## 架构

```
┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────┐
│  上游源聚合  │──▶│ 解析/归一/去重 │──▶│  健康探测    │──▶│  发布     │
│ 5 个上游     │   │ 别名合并      │   │ 存活率 54.9% │   │ m3u/json │
└─────────────┘   └──────────────┘   └─────────────┘   └────┬─────┘
                                                             │
                        ┌────────────────────────────────────┘
                        ▼
                 ┌─────────────┐        ┌──────────────┐
                 │  TCL 电视    │◀──────▶│  手机浏览器   │
                 │  播放器订阅   │ 局域网  │  换源/换台    │
                 └─────────────┘  HTTP  └──────────────┘
```

---

## 快速开始

### 1. 跑一次聚合

```bash
pip install aiohttp
python -m iptvhub.cli --out dist
```

产物在 `dist/`：

| 文件 | 用途 |
|---|---|
| `live.m3u` | 标准 m3u，任何播放器都能用 |
| `live_multi.m3u` | **带备用源**的 m3u，配改造版播放器自动切换 |
| `live.txt` | `频道名,url` 格式 |
| `tvbox.json` | TVBox / FongMi 直接用 |
| `stats.json` | 存活率统计 |
| `audit_hosts.json` | 域名审计（排查垃圾源用） |

### 2. 部署定时任务

推到 GitHub，`.github/workflows/aggregate.yml` 每 6 小时自动跑一次。

订阅地址（固定不变）：
```
https://ghproxy.net/https://raw.githubusercontent.com/你的用户名/iptv-hub/main/dist/live_multi.m3u
```

> ⚠️ **国内必须走 `ghproxy.net` 代理**。实测 `raw.githubusercontent.com`、`cdn.jsdelivr.net`、
> `gh-proxy.com` 全部超时，只有 `ghproxy.net` 可用（~3.9s）。

### 3. 电视端安装

```bash
adb connect 192.168.x.x:5555
adb install -r TCLPlayer.apk
adb shell monkey -p com.home.tcltv.player 1
```

### 4. 手机端换源

电视播放器启动后，手机上打开：
```
http://电视IP:8080
```
输入电视上显示的 6 位配对码即可。

---

## 核心模块

| 模块 | 职责 | 关键设计 |
|---|---|---|
| `fetcher.py` | 多上游并发抓取 | 镜像回退链 + IDN 中文域名转码 |
| `parsers/` | m3u / txt / TVBox 解析 | 状态机容错 + 二级订阅递归展开 |
| `normalize.py` | 频道名归一化 | CCTV1 = CCTV-1 = 中央1台 = 央视一套 |
| `filtering.py` | 三级过滤 | **域名黑名单** + 电台剔除 + 名字合法性 |
| `probe.py` | 健康探测 | 流特征识别（m3u8 magic / TS 同步字节） |
| `writers.py` | 输出 | `#EXTM3U-FALLBACK` 承载备用源 |
| `quality.py` | 统计告警 | 存活率趋势 + Server酱/Telegram 推送 |

### 归一化：多源合并的前提

没有归一化，`CCTV1`、`CCTV-1`、`中央1台`、`央视一套` 会被当成 4 个不同频道，
"同一频道的多个备用源"就无从谈起。内置别名表覆盖 CCTV-1~17 和全国卫视。

### 三级过滤：本方案的关键

实测发现**光靠名字过滤完全不够**。第一版聚合出 167,775 条，其中 97% 是垃圾：

```
em.21dtv.com        162,384 条  kw=0.011  song=0.915  -> 音乐站
vd2.bdstatic.com        224 条  kw=0.004  song=0.009  -> 百度网盘 CDN
antiserver.kuwo.cn        —      —         —         -> 酷我音乐
```

注意 `vd2.bdstatic.com` 的歌曲率只有 0.009，**靠"歌手-歌名"形态根本判不出来**。
所以主判据改成 **`kw_ratio`（频道特征词命中率）** —— 真源如
`ottrrs.hl.chinamobile.com` 是 0.81，垃圾源低于 0.03，区分度极高。

### 备用源格式

`live_multi.m3u` 用自定义扩展行承载备用地址：

```m3u
#EXTINF:-1 tvg-name="江苏体育" group-title="体育" source-count="3",江苏体育
#EXTM3U-FALLBACK:http://183.207.249.12/...|http://223.110.245.157/...
http://183.207.248.71/gitv/live1/G_JSTY/G_JSTY
```

改造版播放器解析 `#EXTM3U-FALLBACK` 后，主源失败可自动切到备用源。

---

## 手机远程换源

### 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/pair` | 用 6 位 PIN 换 token |
| GET | `/api/status` | 当前状态（频道数/存活数/播放中） |
| POST | `/api/source` | 切换订阅源 `{url}` |
| POST | `/api/refresh` | 立即刷新 |
| GET | `/api/channels` | 频道列表 `?offset=&limit=&q=` |
| POST | `/api/play` | 切台 `{name, index}` |
| GET | `/api/pin` | 查询配对码 |

### 安全设计

- **只监听局域网** —— 校验来源 IP 属于同网段，非本网段直接 403
- **PIN 配对** —— 首次连接需输入电视上显示的 6 位码
- **token 鉴权** —— 之后所有接口校验 `X-Token` 头
- **请求体上限** 64KB，防内存耗尽

### 集成步骤

1. 拷贝 `remote/` 下 4 个文件到播放器工程
2. Application 里启动服务：
   ```java
   RemoteControlServer server = new RemoteControlServer(this, 8080,
           new TvControlBridge(this));
   server.start();
   Log.i("Remote", "配对码: " + server.getPin());
   ```
3. 把 `TvControlBridge` 里的 `// 实际项目里替换为...` 注释处接到播放器自身逻辑

`remote/WebPage.java` 由 `build_webpage.py` 从 `remote_web.html` 自动生成，改完 HTML 记得重跑。

---

## TCL 电视适配

### 先确认系统类型

```bash
adb shell getprop ro.com.google.clientidbase
```

| 结果 | 系统 | 装法 |
|---|---|---|
| 有值 | Google TV | 直接 `adb install` |
| 空 + `ro.ffalcon.*` | 雷鸟定制 | 需关安装校验 |
| 空 + `ro.tcl.*` | 灵控/自研 | 可能要 U 盘装 |

### 常见失败处理

```bash
# 关安装校验
adb shell settings put global verifier_verify_adb_installs 0
adb shell settings put global package_verifier_enable 0

# 签名不一致导致装不上（系统预装同名包）
adb shell pm uninstall -k --user 0 原包名

# 关机自启失效（TCL 关机是深度待机，BOOT_COMPLETED 不派发）
# 最稳的办法：设为默认桌面
adb shell cmd package set-home-activity com.home.tcltv.player/.ui.activity.HomeActivity
```

---

## 上手指南

| 阶段 | 工作量 | 做什么 |
|---|---|---|
| **能看** | 半天 | 跑聚合 → 拿 `live.m3u` → 装现成播放器填订阅 |
| **稳定** | +1 天 | 推 GitHub 开 Actions → 用 `live_multi.m3u` |
| **可管** | +2 天 | 编播放器加远程控制 → 手机换源 |

环境依赖：Python 3.10+ / aiohttp；改播放器另需 JDK 17 + Android SDK 34。

---

## 已知限制

1. **上游会挂** —— `iptv-org` 的 `index.m3u`、`cn_sichuan.m3u` 实测已 404。
   加新上游前先 `curl -I` 验证路径。
2. **二级订阅成功率约 50%** —— 16 个二级源里稳定成功的只有 7~8 个，
   依赖 `github.moeyy.xyz` 等第三方代理，本身也不稳定。
3. **移动运营商源最优质** —— `ottrrs.hl.chinamobile.com` 这类特征词率高、存活好，
   但可能有地域限制。
4. **`#EXTM3U-FALLBACK` 是私有扩展** —— 标准播放器会忽略它（不影响播放），
   只有改造版能利用备用源。

---

## 目录结构

```
iptv-hub/
├── iptvhub/
│   ├── config.py        上游清单与参数
│   ├── fetcher.py       并发抓取 + 镜像回退
│   ├── parsers/         m3u / txt / tvbox 解析
│   ├── normalize.py     频道名归一化
│   ├── filtering.py     三级过滤
│   ├── probe.py         健康探测
│   ├── writers.py       输出
│   ├── quality.py       统计告警
│   └── cli.py           主流程
├── remote/              手机远程控制
│   ├── RemoteControlServer.java   HTTP 服务
│   ├── TvControlBridge.java       播放器桥接
│   ├── remote_web.html            手机页面
│   └── WebPage.java               自动生成
├── .github/workflows/aggregate.yml
├── build_webpage.py     HTML 转 Java
└── dist/                输出产物
```
