# 自建下载站（fnos WebDAV）

自定义客户端的「下载新版本」按钮不再跳 `rustdesk.com/download`（它只重定向到 GitHub）。
现在指向本站，安装包存在 fnos 的 WebDAV 上，不占用 aircore.top 服务器本地磁盘（根分区只剩约 8 GB 可用）。

**入口**：<https://rustdesk.aircore.top:8888/download/> → 302 → `latest.html`

## 数据流

```
GitHub Actions 构建产物 dist/*
   │  MKCOL + curl -T（WebDAV Basic 认证）
   ▼
fnos WebDAV  http://192.168.3.43:5005/WebDAV/rustdesk-download/<version>/
   │  nginx 反向代理（只读，代填认证）
   ▼
访客  https://rustdesk.aircore.top:8888/download/<version>/<file>
```

CI **不参与**下载站同步。三个构建 workflow 只负责编译并把产物发布到 GitHub release。
下载站由 aircore.top 上的同步脚本从 GitHub 拉取产物后发布（见下）。
每次同步生成两个页面：

- `<version>/index.html` — 该版本的文件列表
- `latest.html` — 固定地址，只指向最新版本，客户端按钮指向它

## 服务器配置

文件：`/etc/nginx/sites-available/rustdesk.conf`（Panther-X2 / aircore.top）

```nginx
location = /download/  { return 302 /download/latest.html; }
location = /download    { return 302 /download/latest.html; }

location ^~ /download/ {
    limit_except GET HEAD { deny all; }
    include snippets/webdav_download_auth.conf;
    proxy_hide_header WWW-Authenticate;
    index index.html;
    rewrite ^/download/(.+)/$ /download/$1/index.html last;
    proxy_pass http://192.168.3.43:5005/WebDAV/rustdesk-download/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_connect_timeout 15s;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    proxy_request_buffering off;
}
```

几个点不能去掉：

- **`limit_except GET HEAD`**：WebDAV 后端支持 `PUT`/`PROPFIND`/`DELETE`/`MOVE` 等方法。
  代理会代填 Basic 认证头，若不限制方法，公网就能通过这些方法直接写底层 fnos 共享目录。
  2026-11-26 的审计补上了这条，实测 `OPTIONS`/`PROPFIND`/`POST` 均返回 403。
- **`proxy_hide_header WWW-Authenticate`**：避免公开的 200 响应把 Basic Auth 提示头发给访客。
- **`rewrite ^/download/(.+)/$`**：WebDAV 不提供目录列表，直接 GET 目录会 405；
  必须映射到该目录预先上传的 `index.html`。
- **两个精确 location**：`/download` 和 `/download/` 都重定向到 `latest.html`，否则根路径 405。

WebDAV 凭据的代理侧配置在 `/etc/nginx/snippets/webdav_download_auth.conf`，权限 `600 root:root`：

```nginx
proxy_set_header Authorization "Basic <base64(user:pass)>";
```

凭据来自 fnos 的 SMB 账户（`/etc/smbcredentials`）。改动后需重新生成 base64 并重载 nginx。

另外，2026-11-26 的审计把 `/etc/nginx/snippets/ssl_cert.conf` 的 HSTS 从
`max-age=31536000; includeSubDomains; preload` 收敛为 `max-age=31536000`，
避免影响独立的 `hz.aircore.top` 和非 HTTPS 端口。

## 同步脚本（服务器端）

```bash
# 从 GitHub release 拉产物（经本地 Clash 7890），再走内网 PUT 到 fnos
/usr/local/bin/rustdesk-sync-release.sh 1.5.3-2
```

脚本流程：

1. `curl -x http://127.0.0.1:7890` 调 GitHub API 取 release 资产列表
2. 逐个下载产物到 `/tmp/rustdesk-sync-<tag>/`（跳过 update sidecar 和 API 元数据）
3. 调用 `rustdesk-webdav-publish.sh` 从内网 PUT 到 fnos，并生成 index.html / latest.html
4. 清理临时目录

实测完整同步（`1.5.3-2` 的 6 个产物约 170MB）约 2 分钟，产物大小和 GitHub release 完全一致。
Clash 是必需的：服务器直连 GitHub 2 分钟只有 1MB，经 Clash 25MB 约 6 秒。

## GitHub 配置

| 类型 | 名称 | 值 |
|---|---|---|
| Secret | `WEBDAV_USER` | fnos 账户名 |
| Secret | `WEBDAV_PASSWORD` | fnos 账户密码 |
CI 不再持有任何下载站相关 secret 或 SSH 密钥（已清理）。
WebDAV 凭据只在服务器 `/etc/nginx/snippets/webdav_download_auth.conf`，同步脚本直接复用该文件，不存第三份。

## 客户端链接

补丁 `patches/130-download-site.patch` 替换了两处上游硬编码的 `https://rustdesk.com/download`：

- `flutter/lib/mobile/pages/connection_page.dart`（手机端粉色更新条）
- `flutter/lib/desktop/pages/desktop_home_page.dart`（桌面端下载卡片）

都改为 `https://rustdesk.aircore.top:8888/download/latest.html`。
注意：**已发布的 1.5.3-2 里没有这个补丁**，需要重新构建发布才会生效。

## 验证

在 aircore.top 上执行：

```bash
nginx -t && nginx -s reload

# 匿名只读
curl -sk -o /dev/null -w 'GET: %{http_code}\n' \
  --resolve rustdesk.aircore.top:8888:127.0.0.1 \
  https://rustdesk.aircore.top:8888/download/latest.html          # 200
curl -sk -o /dev/null -w 'root: %{http_code} -> %{redirect_url}\n' \
  --resolve rustdesk.aircore.top:8888:127.0.0.1 \
  https://rustdesk.aircore.top:8888/download/                     # 302 -> latest.html

# 写方法必须被拦下
curl -sk -o /dev/null -w 'OPTIONS: %{http_code}\n' -X OPTIONS \
  --resolve rustdesk.aircore.top:8888:127.0.0.1 \
  https://rustdesk.aircore.top:8888/download/latest.html          # 403
curl -sk -o /dev/null -w 'PROPFIND: %{http_code}\n' -X PROPFIND -H 'Depth: 0' \
  --resolve rustdesk.aircore.top:8888:127.0.0.1 \
  https://rustdesk.aircore.top:8888/download/latest.html          # 403

# 认证文件权限
stat -c '%a %U:%G' /etc/nginx/snippets/webdav_download_auth.conf  # 600 root:root
```

手工上传测试：

```bash
AUTH="Basic <base64(user:pass)>"
BASE="http://192.168.3.43:5005/WebDAV/rustdesk-download/1.5.3-2"
curl -X MKCOL -H "Authorization: $AUTH" "$BASE/"
curl -T package.exe -H "Authorization: $AUTH" "$BASE/package.exe"
```

## 回滚

2026-11-26 审计前的完整备份在 `/root/nginx-audit-backup-20261126-154133/`
（含 `conf.d/`、`sites-available/`、`sites-enabled/`、`snippets/`、`nginx.conf`，目录权限 700）。
恢复前先 `nginx -t`，再 `nginx -s reload`。注意该备份**不含**下载站配置，
直接整目录覆盖会把 `/download/` 一起删掉。

相关提交：`ad0a8b1`（下载站 + 补丁 130）、`85cb023`（文档）、`1b04331`（已回退的 SSH 方案）。
CI 上传逻辑已全部移除，同步脚本只存在于服务器 `/usr/local/bin/`。
审计会话：Antigravity `018b7595-5d60-48e6-b778-bddeafd5e83a`（Nginx Configuration Optimization Review）。
