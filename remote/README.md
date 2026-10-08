# -*- coding: utf-8 -*-
"""
IPTV 远程控制服务（电视端 HTTP 服务）。

设计目标：
    手机连同一 WiFi，浏览器打开 http://电视IP:8080 即可：
      - 查看当前播放状态
      - 切换订阅源
      - 手动触发刷新
      - 直接让电视切到指定频道

架构：
    NanoHTTPD 风格的最小 HTTP 服务（纯 Java，无第三方依赖），
    与播放器同进程运行，通过回调接口与播放器交互。

安全：
    - 只监听局域网，校验来源 IP 属于同网段
    - 首次配对生成 6 位 PIN，换取 token
    - token 存 SharedPreferences，可重置

集成方式（在播放器的 Application 或主 Activity 中）：
    RemoteControlServer server = new RemoteControlServer(this, 8080, callback);
    server.start();

package com.home.tcltv.remote;
"""
from __future__ import annotations

# 本文件是 Android 端 Java 代码的设计稿 + 配套 Python 参考实现。
# 见同目录 remote_server.java / remote_web.html
