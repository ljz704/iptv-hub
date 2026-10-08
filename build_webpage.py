# -*- coding: utf-8 -*-
"""把 remote_web.html 内嵌为 Java 常量，生成 WebPage.java。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

html = open('remote/remote_web.html', encoding='utf-8').read()

# 转义为 Java 字符串字面量
escaped = (html.replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace('\r\n', '\\n')
                .replace('\n', '\\n'))

# 分段拼接，避免单行过长超出 JVM 方法字节码限制
CHUNK = 4000
parts = [escaped[i:i + CHUNK] for i in range(0, len(escaped), CHUNK)]
body = '\n            + '.join(f'"{p}"' for p in parts)

java = f'''package com.home.tcltv.remote;

/**
 * 手机端控制页面的 HTML（由 remote_web.html 自动生成，勿手改）。
 *
 * <p>重新生成：python build_webpage.py
 */
final class WebPage {{
    private WebPage() {{}}

    static final String HTML =
            {body};
}}
'''

open('remote/WebPage.java', 'w', encoding='utf-8').write(java)
print(f'已生成 remote/WebPage.java')
print(f'  HTML 原始长度: {len(html)} 字符')
print(f'  转义后长度:   {len(escaped)}')
print(f'  分段数:       {len(parts)}')
