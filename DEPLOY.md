# 部署到 GitHub —— 傻瓜式步骤

目标：把配置发布成一个**永久 URL**，电视上的 TVBox 填一次就不管了。

---

## 一、创建仓库

1. 打开 https://github.com/new
2. **Repository name** 填：`iptv-hub`
3. 选 **Public**（私有仓库的 raw 链接需要 token，电视上不好填）
4. **不要**勾选 "Add a README file"
5. 点 **Create repository**

---

## 二、推送代码

在 `C:\Users\lqt\Desktop\电视软件\iptv-hub` 目录下执行：

```powershell
cd "C:\Users\lqt\Desktop\电视软件\iptv-hub"

git init
git add .
git commit -m "feat: IPTV 源聚合 + 点播搜索"
git branch -M main
git remote add origin https://github.com/ljz704/iptv-hub.git
git push -u origin main
```

推送时会弹窗要账号密码：
- **用户名**：`ljz704`
- **密码**：⚠️ **不是你的登录密码**，要用 **Personal Access Token**

### 获取 Token（30 秒）

1. 打开 https://github.com/settings/tokens
2. **Generate new token** → **classic**
3. Note 填 `iptv`，Expiration 选 `No expiration`
4. 勾选 **`repo`**（完整仓库权限）
5. 点 **Generate token**，**复制那串 `ghp_xxxxx`**
6. 回到 PowerShell 粘贴作为密码

> Token 只显示一次，先存记事本里。

---

## 三、拿到订阅地址

推送成功后，你的配置地址就是：

```
https://ghproxy.net/https://raw.githubusercontent.com/ljz704/iptv-hub/main/dist/tvbox.json
```

> 国内直连 `raw.githubusercontent.com` 会超时（实测过），
> **必须**用 `ghproxy.net` 前缀。

---

## 四、开启自动更新（可选）

仓库里的 `.github/workflows/aggregate.yml` 已经写好了，每 6 小时自动：

1. 抓取最新源
2. 健康探测剔除死源
3. 提交更新

**要生效需要**：仓库 **Settings → Actions → General → Workflow permissions**
选 **Read and write permissions** → Save。

---

## 五、电视上装 TVBox

1. 把 `apk/leanback-arm64_v8a.apk` 拷到 U 盘
2. 电视插 U 盘 → 文件管理器打开 APK → 安装
   （需先在 设置 → 安全 → 允许未知来源）
3. 打开 App → **设置 → 配置地址** → 填入第三步那个 URL
4. 返回首页 → 直播能看到频道，搜索能搜剧

---

## 备用：本地服务器方式

如果暂时不想推 GitHub，用电脑当服务器：

```powershell
cd "C:\Users\lqt\Desktop\电视软件\iptv-hub\dist"
python -m http.server 8899 --bind 0.0.0.0
```

电视上填：
```
http://你电脑的局域网IP:8899/tvbox.json
```

查电脑 IP：
```powershell
ipconfig | Select-String "IPv4"
```

⚠️ 缺点：电脑必须一直开着。
