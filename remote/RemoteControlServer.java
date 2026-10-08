package com.home.tcltv.remote;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedOutputStream;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * IPTV 远程控制服务 —— 手机端通过浏览器管理电视播放器。
 *
 * <p>特性：
 * <ul>
 *   <li>零第三方依赖，纯 JDK + Android SDK</li>
 *   <li>只监听局域网，校验来源网段</li>
 *   <li>6 位 PIN 配对 + token 鉴权</li>
 *   <li>提供换源、刷新、换台、状态查询接口</li>
 * </ul>
 *
 * <p>用法：
 * <pre>
 *   RemoteControlServer server = new RemoteControlServer(context, 8080, callback);
 *   server.start();
 *   // 退出时
 *   server.stop();
 * </pre>
 *
 * @author home-tv
 */
public class RemoteControlServer {

    private static final String TAG = "RemoteCtl";
    private static final String PREFS = "remote_ctl";
    private static final String KEY_TOKEN = "token";
    private static final String KEY_PIN = "pin";

    /** 允许的最大请求体，防止内存耗尽 */
    private static final int MAX_BODY = 64 * 1024;
    /** 单连接读超时（毫秒） */
    private static final int SO_TIMEOUT = 10_000;

    // ------------------------------------------------------------ 回调

    /**
     * 播放器需要实现的回调接口。
     */
    public interface Callback {
        /** @return 当前状态 JSON，字段见 buildStatus */
        JSONObject onStatus();

        /**
         * 切换订阅源。
         * @param url  新的订阅地址（m3u / txt / tvbox json）
         * @return 是否接受
         */
        boolean onSetSource(String url);

        /** 立即刷新源 */
        boolean onRefresh();

        /**
         * 切换到指定频道。
         * @param name  频道名
         * @param index 使用第几个备用源，0 为主源
         * @return 是否成功
         */
        boolean onPlayChannel(String name, int index);

        /** @return 可选源列表 */
        JSONArray onListSources();

        /** @return 频道列表（分页） */
        JSONArray onListChannels(int offset, int limit, String keyword);
    }

    // ------------------------------------------------------------ 字段

    private final Context context;
    private final int port;
    private final Callback callback;
    private final SharedPreferences prefs;
    private final ExecutorService pool = Executors.newFixedThreadPool(4);
    private final AtomicBoolean running = new AtomicBoolean(false);

    private ServerSocket serverSocket;
    private Thread acceptThread;

    /** 已授权 token 集合（内存态，重启后从 prefs 恢复） */
    private final List<String> tokens = new ArrayList<>();

    /** 本机内网前缀，用于校验来源，如 "192.168.1." */
    private String localPrefix = "";

    public RemoteControlServer(Context context, int port, Callback callback) {
        this.context = context.getApplicationContext();
        this.port = port;
        this.callback = callback;
        this.prefs = this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String t = prefs.getString(KEY_TOKEN, null);
        if (t != null && !t.isEmpty()) {
            tokens.add(t);
        }
    }

    // ------------------------------------------------------------ 生命周期

    /** 启动服务。已在运行则直接返回。 */
    public void start() {
        if (!running.compareAndSet(false, true)) {
            return;
        }
        localPrefix = detectLocalPrefix();

        acceptThread = new Thread(this::acceptLoop, "remote-ctl-accept");
        acceptThread.setDaemon(true);
        acceptThread.start();
        Log.i(TAG, "远程控制服务已启动，端口 " + port + "，网段 " + localPrefix);
    }

    /** 停止服务。 */
    public void stop() {
        running.set(false);
        try {
            if (serverSocket != null) {
                serverSocket.close();
            }
        } catch (IOException ignored) {
        }
        serverSocket = null;
        pool.shutdownNow();
        Log.i(TAG, "远程控制服务已停止");
    }

    /** @return 是否运行中 */
    public boolean isRunning() {
        return running.get();
    }

    /** @return 服务端口 */
    public int getPort() {
        return port;
    }

    /** @return 当前配对 PIN，用于电视上展示 */
    public String getPin() {
        return prefs.getString(KEY_PIN, "");
    }

    /** 重置配对：清空 token 并生成新 PIN。 */
    public String resetPairing() {
        String pin = String.format(Locale.US, "%06d", new SecureRandom().nextInt(1_000_000));
        tokens.clear();
        prefs.edit().putString(KEY_PIN, pin).remove(KEY_TOKEN).apply();
        return pin;
    }

    // ------------------------------------------------------------ 网络

    private String detectLocalPrefix() {
        try {
            java.util.Enumeration<java.net.NetworkInterface> ifaces =
                    java.net.NetworkInterface.getNetworkInterfaces();
            while (ifaces.hasMoreElements()) {
                java.net.NetworkInterface ni = ifaces.nextElement();
                if (ni.isLoopback() || !ni.isUp()) {
                    continue;
                }
                java.util.Enumeration<InetAddress> addrs = ni.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress a = addrs.nextElement();
                    if (a instanceof java.net.Inet4Address && !a.isLoopbackAddress()) {
                        String ip = a.getHostAddress();
                        int dot = ip.lastIndexOf('.');
                        if (dot > 0) {
                            return ip.substring(0, dot + 1);
                        }
                    }
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "探测本地网段失败", e);
        }
        return "";
    }

    private boolean isLocalClient(String remoteIp) {
        if (localPrefix.isEmpty()) {
            return true;
        }
        if (remoteIp == null) {
            return false;
        }
        // 本机回环也放行，方便 adb forward 调试
        if (remoteIp.startsWith("127.")) {
            return true;
        }
        return remoteIp.startsWith(localPrefix);
    }

    private void acceptLoop() {
        try {
            serverSocket = new ServerSocket();
            serverSocket.setReuseAddress(true);
            serverSocket.bind(new InetSocketAddress(port));
        } catch (IOException e) {
            Log.e(TAG, "绑定端口 " + port + " 失败", e);
            running.set(false);
            return;
        }

        while (running.get()) {
            try {
                final Socket sock = serverSocket.accept();
                pool.execute(() -> handle(sock));
            } catch (IOException e) {
                if (running.get()) {
                    Log.w(TAG, "accept 异常", e);
                }
            }
        }
    }

    // ------------------------------------------------------------ 请求处理

    private void handle(Socket sock) {
        String remoteIp = sock.getInetAddress() != null
                ? sock.getInetAddress().getHostAddress() : null;

        try (Socket s = sock) {
            s.setSoTimeout(SO_TIMEOUT);

            if (!isLocalClient(remoteIp)) {
                writeJson(s, 403, err("非局域网访问已拒绝"));
                return;
            }

            BufferedReader in = new BufferedReader(
                    new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));

            String requestLine = in.readLine();
            if (requestLine == null || requestLine.isEmpty()) {
                return;
            }

            String[] parts = requestLine.split(" ");
            if (parts.length < 2) {
                writeJson(s, 400, err("请求行格式错误"));
                return;
            }
            String method = parts[0];
            String path = parts[1];

            // 解析请求头
            Map<String, String> headers = new HashMap<>();
            String line;
            int contentLength = 0;
            while ((line = in.readLine()) != null && !line.isEmpty()) {
                int colon = line.indexOf(':');
                if (colon > 0) {
                    String k = line.substring(0, colon).trim().toLowerCase(Locale.US);
                    String v = line.substring(colon + 1).trim();
                    headers.put(k, v);
                    if ("content-length".equals(k)) {
                        try {
                            contentLength = Integer.parseInt(v);
                        } catch (NumberFormatException ignored) {
                        }
                    }
                }
            }

            // 读取请求体
            String body = "";
            if (contentLength > 0 && contentLength <= MAX_BODY) {
                char[] buf = new char[contentLength];
                int read = 0;
                while (read < contentLength) {
                    int n = in.read(buf, read, contentLength - read);
                    if (n < 0) {
                        break;
                    }
                    read += n;
                }
                body = new String(buf, 0, read);
            }

            route(s, method, path, headers, body);
        } catch (Exception e) {
            Log.w(TAG, "处理请求异常", e);
        }
    }

    private void route(Socket s, String method, String path,
                       Map<String, String> headers, String body) throws IOException {

        // 路由与查询串分离
        String query = "";
        int q = path.indexOf('?');
        if (q >= 0) {
            query = path.substring(q + 1);
            path = path.substring(0, q);
        }

        // 静态首页不需要鉴权
        if ("/".equals(path) || "/index.html".equals(path)) {
            servePage(s);
            return;
        }

        // 配对接口不需要鉴权
        if ("/api/pair".equals(path)) {
            handlePair(s, body);
            return;
        }

        // 其余接口需要 token
        if (!authorized(headers, query)) {
            writeJson(s, 401, err("未授权，请先配对"));
            return;
        }

        switch (path) {
            case "/api/status":
                writeJson(s, 200, callback != null ? callback.onStatus() : ok());
                break;

            case "/api/source":
                handleSetSource(s, method, body);
                break;

            case "/api/refresh":
                writeJson(s, 200, simpleResult(callback != null && callback.onRefresh()));
                break;

            case "/api/sources":
                writeJson(s, 200, listResult(callback != null
                        ? callback.onListSources() : new JSONArray()));
                break;

            case "/api/channels":
                handleChannels(s, query);
                break;

            case "/api/play":
                handlePlay(s, method, body);
                break;

            case "/api/pin":
                writeJson(s, 200, ok().put("pin", getPin()));
                break;

            default:
                writeJson(s, 404, err("未知接口 " + path));
        }
    }

    private boolean authorized(Map<String, String> headers, String query) {
        String token = headers.get("x-token");
        if (token == null || token.isEmpty()) {
            for (String kv : query.split("&")) {
                int eq = kv.indexOf('=');
                if (eq > 0 && "token".equals(kv.substring(0, eq))) {
                    token = urlDecode(kv.substring(eq + 1));
                    break;
                }
            }
        }
        return token != null && tokens.contains(token);
    }

    private void handlePair(Socket s, String body) throws IOException {
        JSONObject req = parseJson(body);
        String pin = req.optString("pin", "");
        String expect = prefs.getString(KEY_PIN, null);

        if (expect == null || expect.isEmpty()) {
            // 首次使用，自动生成
            expect = resetPairing();
        }

        if (!expect.equals(pin)) {
            writeJson(s, 401, err("配对码错误"));
            return;
        }

        String token = newToken();
        tokens.add(token);
        prefs.edit().putString(KEY_TOKEN, token).apply();
        writeJson(s, 200, ok().put("token", token));
        Log.i(TAG, "配对成功，已签发 token");
    }

    private void handleSetSource(Socket s, String method, String body) throws IOException {
        if (!"POST".equals(method)) {
            writeJson(s, 405, err("请用 POST"));
            return;
        }
        JSONObject req = parseJson(body);
        String url = req.optString("url", "").trim();
        if (url.isEmpty()) {
            writeJson(s, 400, err("缺少 url 参数"));
            return;
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            writeJson(s, 400, err("url 必须以 http 开头"));
            return;
        }
        boolean okResult = callback != null && callback.onSetSource(url);
        writeJson(s, 200, simpleResult(okResult).put("url", url));
    }

    private void handlePlay(Socket s, String method, String body) throws IOException {
        if (!"POST".equals(method)) {
            writeJson(s, 405, err("请用 POST"));
            return;
        }
        JSONObject req = parseJson(body);
        String name = req.optString("name", "").trim();
        int index = req.optInt("index", 0);
        if (name.isEmpty()) {
            writeJson(s, 400, err("缺少 name 参数"));
            return;
        }
        boolean okResult = callback != null && callback.onPlayChannel(name, index);
        writeJson(s, 200, simpleResult(okResult).put("name", name).put("index", index));
    }

    private void handleChannels(Socket s, String query) throws IOException {
        int offset = 0;
        int limit = 100;
        String keyword = "";
        for (String kv : query.split("&")) {
            int eq = kv.indexOf('=');
            if (eq <= 0) {
                continue;
            }
            String k = kv.substring(0, eq);
            String v = urlDecode(kv.substring(eq + 1));
            if ("offset".equals(k)) {
                offset = parseInt(v, 0);
            } else if ("limit".equals(k)) {
                limit = Math.min(parseInt(v, 100), 500);
            } else if ("q".equals(k)) {
                keyword = v;
            }
        }
        JSONArray arr = callback != null
                ? callback.onListChannels(offset, limit, keyword) : new JSONArray();
        writeJson(s, 200, ok().put("items", arr).put("offset", offset));
    }

    // ------------------------------------------------------------ 响应

    private void servePage(Socket s) throws IOException {
        String html = WebPage.HTML;
        byte[] bytes = html.getBytes(StandardCharsets.UTF_8);
        OutputStream out = new BufferedOutputStream(s.getOutputStream());
        out.write(("HTTP/1.1 200 OK\r\n"
                + "Content-Type: text/html; charset=utf-8\r\n"
                + "Content-Length: " + bytes.length + "\r\n"
                + "Cache-Control: no-store\r\n"
                + "Connection: close\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(bytes);
        out.flush();
    }

    private void writeJson(Socket s, int code, JSONObject obj) throws IOException {
        byte[] bytes = obj.toString().getBytes(StandardCharsets.UTF_8);
        String reason = code == 200 ? "OK"
                : code == 400 ? "Bad Request"
                : code == 401 ? "Unauthorized"
                : code == 403 ? "Forbidden"
                : code == 404 ? "Not Found"
                : code == 405 ? "Method Not Allowed" : "Error";

        OutputStream out = new BufferedOutputStream(s.getOutputStream());
        out.write(("HTTP/1.1 " + code + " " + reason + "\r\n"
                + "Content-Type: application/json; charset=utf-8\r\n"
                + "Content-Length: " + bytes.length + "\r\n"
                + "Cache-Control: no-store\r\n"
                + "Connection: close\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(bytes);
        out.flush();
    }

    // ------------------------------------------------------------ 工具

    private static JSONObject ok() {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
        } catch (Exception ignored) {
        }
        return o;
    }

    private static JSONObject err(String msg) {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", false).put("error", msg);
        } catch (Exception ignored) {
        }
        return o;
    }

    private static JSONObject simpleResult(boolean success) {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", success);
        } catch (Exception ignored) {
        }
        return o;
    }

    private static JSONObject listResult(JSONArray arr) {
        JSONObject o = ok();
        try {
            o.put("items", arr);
        } catch (Exception ignored) {
        }
        return o;
    }

    private static JSONObject parseJson(String body) {
        if (body == null || body.trim().isEmpty()) {
            return new JSONObject();
        }
        try {
            return new JSONObject(body);
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    private static int parseInt(String s, int def) {
        try {
            return Integer.parseInt(s);
        } catch (Exception e) {
            return def;
        }
    }

    private static String urlDecode(String s) {
        try {
            return URLDecoder.decode(s, "UTF-8");
        } catch (Exception e) {
            return s;
        }
    }

    private static String newToken() {
        byte[] raw = new byte[24];
        new SecureRandom().nextBytes(raw);
        StringBuilder sb = new StringBuilder();
        for (byte b : raw) {
            sb.append(String.format(Locale.US, "%02x", b));
        }
        return sb.toString();
    }
}
