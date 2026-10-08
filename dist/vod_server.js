#!/usr/bin/env node
/**
 * 点播搜索代理服务（Node.js）
 *
 * 作用：代理苹果CMS采集接口，绕开浏览器的 CORS 限制，
 *       让网页端可以直接搜索剧集。
 *
 * 实测可用的公开采集接口：
 *   bfzyapi.com          暴風资源   （苹果CMS，开放）
 *   api.apibdzy.com      百度资源   （苹果CMS，开放）
 *
 * 用法：node vod_server.js
 */
'use strict';

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const urlMod = require('url');

const PORT = 8900;
const ROOT = __dirname;

// ---------------------------------------------------------------- 采集源
// 实测（关键词「庆余年」）开放的苹果CMS接口。base 结尾必须带斜杠。
const SITES = [
  { name: '暴風资源', base: 'https://bfzyapi.com/api.php/provide/vod/', weight: 10 },
  { name: '百度资源', base: 'https://api.apibdzy.com/api.php/provide/vod/', weight: 5 },
];

// 可从文件追加更多源
try {
  const extra = JSON.parse(fs.readFileSync(path.join(ROOT, 'vod_sources.json'), 'utf8'));
  for (const e of extra) {
    if (e.interface && !SITES.some(s => s.base === e.interface)) {
      SITES.push({ name: e.name, base: e.interface, weight: 3 });
    }
  }
} catch (e) { /* 无附加源，忽略 */ }

// ---------------------------------------------------------------- HTTP 工具
function fetchJson(target, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    let parsed;
    try { parsed = new URL(target); }
    catch (e) { return reject(new Error('非法 URL')); }

    const lib = parsed.protocol === 'https:' ? https : http;
    const req = lib.get(target, {
      timeout: timeoutMs,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, */*',
      }
    }, res => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
        res.resume();
        return fetchJson(new URL(res.headers.location, target).toString(), timeoutMs)
          .then(resolve, reject);
      }
      if (res.statusCode >= 400) {
        res.resume();
        return reject(new Error('HTTP ' + res.statusCode));
      }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        try { resolve(JSON.parse(text)); }
        catch (e) { reject(new Error('响应非 JSON')); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('超时')));
    req.on('error', reject);
  });
}

function sendJson(res, obj, code = 200) {
  const body = JSON.stringify(obj);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function sendFile(res, file, type) {
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, {
      'Content-Type': type,
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store',
    });
    res.end(data);
  });
}

// ---------------------------------------------------------------- 业务
/** 规范化一条搜索结果 */
function normItem(it, siteName) {
  return {
    site: siteName,
    id: String(it.vod_id || it.id || ''),
    name: String(it.vod_name || it.name || '').trim(),
    pic: String(it.vod_pic || it.pic || ''),
    remarks: String(it.vod_remarks || it.remarks || ''),
    year: String(it.vod_year || ''),
    area: String(it.vod_area || ''),
    type: String(it.type_name || ''),
  };
}

async function searchSite(site, wd) {
  const target = `${site.base}?ac=videolist&wd=${encodeURIComponent(wd)}`;
  try {
    const data = await fetchJson(target, 12000);
    const list = data.list || data.data || [];
    const items = (Array.isArray(list) ? list : []).map(it => normItem(it, site.name));
    return { site: site.name, ok: true, count: items.length, items };
  } catch (e) {
    return { site: site.name, ok: false, count: 0, error: e.message, items: [] };
  }
}

async function searchAll(wd) {
  const results = await Promise.all(SITES.map(s => searchSite(s, wd)));
  const ok = results.filter(r => r.items.length > 0);

  // 合并去重：同名剧保留备注信息最全的
  const merged = new Map();
  for (const r of ok) {
    for (const it of r.items) {
      const key = it.name.replace(/\s/g, '');
      if (!merged.has(key)) {
        merged.set(key, { ...it, sources: [it.site] });
      } else {
        const cur = merged.get(key);
        if (!cur.sources.includes(it.site)) cur.sources.push(it.site);
        // 补全缺失字段
        for (const f of ['pic', 'remarks', 'year', 'area', 'type']) {
          if (!cur[f] && it[f]) cur[f] = it[f];
        }
      }
    }
  }

  return {
    keyword: wd,
    totalSites: SITES.length,
    okSites: ok.length,
    total: merged.size,
    items: [...merged.values()],
    perSite: results.map(r => ({
      site: r.site, ok: r.ok, count: r.count, error: r.error || ''
    })),
  };
}

/** 取剧集播放列表 */
async function detail(siteName, id) {
  const site = SITES.find(s => s.name === siteName) || SITES[0];
  const target = `${site.base}?ac=videolist&ids=${encodeURIComponent(id)}`;
  const data = await fetchJson(target, 12000);
  const it = (data.list || [])[0];
  if (!it) throw new Error('未找到该资源');

  // vod_play_url 格式： "第01集$http://...m3u8#第02集$http://..."
  const raw = String(it.vod_play_url || '');
  const flag = String(it.vod_play_from || '').split('$$$');
  const groups = raw.split('$$$');
  const episodes = [];

  groups.forEach((g, gi) => {
    const list = g.split('#').filter(Boolean).map(pair => {
      const [name, epUrl] = pair.split('$');
      return { name: name || '', url: epUrl || '' };
    }).filter(e => e.url);
    if (list.length) {
      episodes.push({ group: flag[gi] || `线路${gi + 1}`, list });
    }
  });

  return {
    site: site.name,
    id,
    name: it.vod_name,
    pic: it.vod_pic,
    remarks: it.vod_remarks,
    episodes,
  };
}

// ---------------------------------------------------------------- 路由
const server = http.createServer(async (req, res) => {
  const u = urlMod.parse(req.url, true);
  const p = u.pathname;

  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': '*',
    });
    return res.end();
  }

  try {
    if (p === '/' || p === '/vod.html' || p === '/index.html') {
      return sendFile(res, path.join(ROOT, 'vod.html'), 'text/html; charset=utf-8');
    }

    if (p === '/api/sites') {
      return sendJson(res, { sites: SITES.map(s => ({ name: s.name, base: s.base })) });
    }

    if (p === '/api/search') {
      const wd = String(u.query.wd || '').trim();
      if (!wd) return sendJson(res, { error: '缺少 wd' }, 400);
      console.log('[搜索] ' + wd);
      const r = await searchAll(wd);
      console.log(`[搜索] ${wd} -> ${r.okSites}/${r.totalSites} 源, 合并 ${r.total} 部`);
      return sendJson(res, r);
    }

    if (p === '/api/detail') {
      const site = String(u.query.site || '');
      const id = String(u.query.id || '');
      if (!id) return sendJson(res, { error: '缺少 id' }, 400);
      const d = await detail(site, id);
      return sendJson(res, d);
    }

    res.writeHead(404); res.end('404');
  } catch (e) {
    sendJson(res, { error: e.message }, 500);
  }
});

// 监听所有网卡，让手机/电视通过局域网访问；仅本机用可改成 '127.0.0.1'
const BIND = process.env.VOD_BIND || '0.0.0.0';

server.listen(PORT, BIND, () => {
  console.log('');
  console.log('  点播搜索服务已启动');
  console.log(`  本机:   http://127.0.0.1:${PORT}/`);
  console.log(`  局域网: http://<本机IP>:${PORT}/`);
  console.log(`  采集源 ${SITES.length} 个: ${SITES.map(s => s.name).join(', ')}`);
  console.log('');
});
