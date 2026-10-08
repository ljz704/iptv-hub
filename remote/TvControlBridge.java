package com.home.tcltv.remote;

import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 远程控制回调的参考实现 —— 演示如何把播放器接进 {@link RemoteControlServer}。
 *
 * <p>集成步骤（以 FongMi/TV 为例）：
 * <ol>
 *   <li>把 remote 包整体拷入 app/src/main/java/com/home/tcltv/remote/</li>
 *   <li>在 Application.onCreate 里创建并启动服务</li>
 *   <li>把 onPlayChannel / onSetSource 接到播放器自身的逻辑</li>
 * </ol>
 *
 * <pre>
 *   // Application
 *   RemoteControlServer server = new RemoteControlServer(
 *           this, 8080, new TvControlBridge(this));
 *   server.start();
 *   Log.i("Remote", "配对码: " + server.getPin());
 * </pre>
 */
public class TvControlBridge implements RemoteControlServer.Callback {

    private static final String TAG = "TvBridge";

    /** 频道 -> 备用源列表（与 m3u 里的 #EXTM3U-FALLBACK 对应） */
    private final Map<String, List<String>> channelSources = new LinkedHashMap<>();

    private final android.content.Context context;

    /** 当前播放的频道名 */
    private String playingChannel = "";

    /** 当前订阅源 */
    private String currentSource = "";

    /** 最后一次刷新时间 */
    private String lastUpdated = "";

    public TvControlBridge(android.content.Context context) {
        this.context = context;
    }

    // ------------------------------------------------------------ 状态

    @Override
    public JSONObject onStatus() {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
            o.put("channels", channelSources.size());
            o.put("alive", countAlive());
            o.put("playing", !playingChannel.isEmpty());
            o.put("nowPlaying", playingChannel);
            o.put("source", currentSource);
            o.put("updated", lastUpdated);
        } catch (Exception e) {
            Log.w(TAG, "构造状态失败", e);
        }
        return o;
    }

    private int countAlive() {
        int n = 0;
        for (List<String> urls : channelSources.values()) {
            if (urls != null && !urls.isEmpty()) {
                n++;
            }
        }
        return n;
    }

    // ------------------------------------------------------------ 换源

    @Override
    public boolean onSetSource(String url) {
        try {
            Log.i(TAG, "切换订阅源: " + url);
            // 实际项目里替换为播放器的源切换逻辑，例如：
            //   Setting.put("sub_url", url);
            //   App.get().getLiveSetting().setUrl(url);
            //   App.get().getLiveDialog()...
            currentSource = url;
            lastUpdated = now();
            // 触发重新拉取
            return reload();
        } catch (Exception e) {
            Log.e(TAG, "切换源失败", e);
            return false;
        }
    }

    @Override
    public boolean onRefresh() {
        Log.i(TAG, "手动刷新源");
        lastUpdated = now();
        return reload();
    }

    /** 重新拉取并解析订阅，填充 channelSources。 */
    private boolean reload() {
        try {
            // 实际项目里：拉取 m3u -> 解析 -> 填充 channelSources
            // 这里给出解析 #EXTM3U-FALLBACK 的逻辑供参考
            String text = fetch(currentSource);
            if (text == null || text.isEmpty()) {
                return false;
            }
            parseM3u(text);
            return true;
        } catch (Exception e) {
            Log.e(TAG, "reload 失败", e);
            return false;
        }
    }

    /** 拉取订阅内容（示例，实际用播放器自带的 OkHttp 实例）。 */
    private String fetch(String url) {
        if (url == null || url.isEmpty()) {
            return null;
        }
        try {
            java.net.HttpURLConnection c =
                    (java.net.HttpURLConnection) new java.net.URL(url).openConnection();
            c.setConnectTimeout(8000);
            c.setReadTimeout(15000);
            c.setRequestProperty("User-Agent", "TCLTV/1.0");
            java.io.InputStream in = c.getInputStream();
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                bos.write(buf, 0, n);
            }
            in.close();
            return new String(bos.toByteArray(), "UTF-8");
        } catch (Exception e) {
            Log.w(TAG, "拉取失败 " + url, e);
            return null;
        }
    }

    /**
     * 解析 m3u，识别本项目输出的 {@code #EXTM3U-FALLBACK} 扩展行。
     *
     * <p>格式：
     * <pre>
     *   #EXTINF:-1 tvg-name="江苏体育" source-count="3",江苏体育
     *   #EXTM3U-FALLBACK:http://备用1|http://备用2
     *   http://主源
     * </pre>
     */
    private void parseM3u(String text) {
        channelSources.clear();
        String pendingName = null;
        List<String> fallbacks = new ArrayList<>();

        for (String raw : text.split("\n")) {
            String line = raw.trim();
            if (line.isEmpty()) {
                continue;
            }

            if (line.startsWith("#EXTM3U-FALLBACK:")) {
                String rest = line.substring("#EXTM3U-FALLBACK:".length());
                fallbacks.clear();
                for (String u : rest.split("\\|")) {
                    if (!u.trim().isEmpty()) {
                        fallbacks.add(u.trim());
                    }
                }
                continue;
            }

            if (line.startsWith("#EXTINF")) {
                int comma = line.lastIndexOf(',');
                pendingName = comma >= 0 ? line.substring(comma + 1).trim() : "";
                continue;
            }

            if (line.startsWith("#")) {
                continue;
            }

            // URL 行
            if (pendingName != null && !pendingName.isEmpty()) {
                List<String> urls = new ArrayList<>();
                urls.add(line);                        // 主源
                urls.addAll(fallbacks);                // 备用源
                channelSources.put(pendingName, urls);
            }
            pendingName = null;
            fallbacks.clear();
        }
        Log.i(TAG, "解析完成，共 " + channelSources.size() + " 个频道");
    }

    // ------------------------------------------------------------ 播放

    @Override
    public boolean onPlayChannel(String name, int index) {
        List<String> urls = channelSources.get(name);
        if (urls == null || urls.isEmpty()) {
            Log.w(TAG, "频道不存在: " + name);
            return false;
        }
        if (index < 0 || index >= urls.size()) {
            index = 0;
        }
        String url = urls.get(index);
        Log.i(TAG, "播放 " + name + " [" + index + "] " + url);

        // 实际项目里替换为播放器跳转逻辑，例如：
        //   LiveActivity.start(context, name, url);
        //   App.get().getPlayer().play(url);
        playingChannel = name;
        return true;
    }

    // ------------------------------------------------------------ 列表

    @Override
    public JSONArray onListSources() {
        JSONArray arr = new JSONArray();
        try {
            JSONObject o = new JSONObject();
            o.put("name", "当前订阅");
            o.put("url", currentSource);
            o.put("active", true);
            o.put("alive", countAlive());
            arr.put(o);
        } catch (Exception e) {
            Log.w(TAG, "构造源列表失败", e);
        }
        return arr;
    }

    @Override
    public JSONArray onListChannels(int offset, int limit, String keyword) {
        JSONArray arr = new JSONArray();
        String kw = keyword == null ? "" : keyword.trim().toLowerCase(Locale.US);

        List<String> names = new ArrayList<>(channelSources.keySet());
        int skipped = 0;
        int added = 0;

        for (String name : names) {
            if (!kw.isEmpty() && !name.toLowerCase(Locale.US).contains(kw)) {
                continue;
            }
            if (skipped < offset) {
                skipped++;
                continue;
            }
            if (added >= limit) {
                break;
            }
            try {
                JSONObject o = new JSONObject();
                o.put("name", name);
                List<String> urls = channelSources.get(name);
                o.put("sources", urls == null ? 0 : urls.size());
                if (urls != null && !urls.isEmpty()) {
                    o.put("url", urls.get(0));
                }
                arr.put(o);
                added++;
            } catch (Exception e) {
                Log.w(TAG, "构造频道项失败", e);
            }
        }
        return arr;
    }

    // ------------------------------------------------------------ 工具

    private static String now() {
        return new java.text.SimpleDateFormat("MM-dd HH:mm", Locale.US)
                .format(new java.util.Date());
    }
}
