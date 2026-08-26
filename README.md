# RustDesk 定制客户端自动构建管线

一套基于 GitHub Actions 的 RustDesk 自定义客户端流水线：**跟随上游版本自动打补丁、编译、发布**，产物为内嵌自建服务器配置的 Windows 安装包，支持无人值守静默访问、三种认证方式并存、自动更新。

> 本仓库为通用模板 —— Fork 后填入你自己的服务器信息（Secrets），即可产出属于你的定制客户端，无需改动任何代码。

## 架构

```
上游 rustdesk/rustdesk 发新版本
        │ 每日定时检测 (upstream-sync.yml)
        ▼
校验补丁可应用 ──失败──▶ 自动开 Issue（附冲突 hunk 定位）
        │ 通过                │
        ▼                     ▼
快速编译门禁 fast-check    （不派发，避免浪费）
        │ ~25 分钟          ▼
│ 失败──▶ 开 Issue 附错误摘要（全量构建不启动）
        │ 通过
        ▼
同步上游构建依赖 pin（变更自动开 Issue 供人工复核）
        ▼
build-windows.yml：检出上游源码 → 注入版本号 → 应用行为补丁
        │            → 由 Secrets 生成 embedded_config.rs → 编译打包
        ▼
发布到本仓库的 Releases（也可用变量指向外部发布仓）
        ▼
已部署的客户端每日检查本仓库 → 弹窗提示 → 一键升级
```

## 功能特性

**客户端行为补丁**（对所有复用者通用）：

- 被控端连接管理窗口无人值守隐藏：任务栏零痕迹，会话静默建立
- 有需要确认的事件（点击授权、UAC 提权、文件确认等）时面板自动唤回；处理完点 X 隐藏面板但**不断开连接**
- 隐藏网络设置页（服务器/代理/WebSocket 配置对最终用户不可见不可改）
- 更新日志链接自动指向上游官方对应版本的 Release 页面
- 软件更新检查指向你自己的发布仓库

**由 Secrets 决定的个性化注入**：

- 内嵌 ID/中继/API 服务器地址与连接公钥（XOR 混淆存储于二进制）
- 内置无人值守固定密码（构建时现算加盐哈希，明文不出现在任何地方）
- 全部以锁定层写入：最终用户在界面中不可见、不可改

## 快速开始（约 5 分钟）

1. **Fork 或使用本仓库模板**创建你自己的仓库（Public，Actions 免费不限量；安装包 Release 也发布在本仓库）
2. **配置 Secrets**（Settings → Secrets and variables → Actions）：见下方参考表
3. **手动触发首次构建**：Actions → Build Windows Custom Client → Run workflow
   - `tag`：上游版本号（如 `1.4.9`）；也可带本地后缀（如 `1.4.9-1`）
   - `upstream_ref`：留空则同 tag；若 tag 带后缀则需填上游真实 tag
4. 构建完成后安装包出现在本仓库 `https://github.com/<你>/<仓库名>/releases`
5. 在目标机器安装即可：服务器配置已内置、无需任何设置

> **可选**：想把安装包发到单独的仓库？设置变量 `RELEASE_REPO` 指向它，并配置有该仓 Contents:write 权限的 `RELEASE_PAT`。不配置则一律发在本仓库，无需任何令牌。

之后全自动：上游发新版 → 凌晨自动过门禁并重建 → 所有已装设备收到更新提示。

## Secrets 与 Variables 参考

| Secret | 必填 | 示例 | 说明 |
|---|---|---|---|
| `RD_ID_SERVER` | ✅ | `hbbs.example.com:21116` | ID 服务器（hbbs）|
| `RD_KEY` | ✅ | `tyW5Z...=` | 服务器 Ed25519 公钥（服务端 `id_ed25519.pub` 文件内容）|
| `RD_RELAY_SERVER` | ➖ | `hbbs.example.com:21117` | 中继服务器（hbbr），缺省自动推导 |
| `RD_API_SERVER` | ➖ | `https://hbbs.example.com:8888` | API 服务器（登录/地址簿），无则留空 |
| `RD_PRESET_PASSWORD` | ➖ | 任意明文 | 内置无人值守密码。构建时计算加盐哈希后嵌入，**明文不会出现在代码、日志或产物之外的任何位置**。不配则不内置密码 |
| `RD_RELEASE_REPO` | ✅* | `you/rustdesk-custom` | 更新检查指向的发布仓（`owner/repo`）。*不配置时默认为本仓库；显式配置则覆盖默认 |
| `RD_WEBSOCKET_ID` | ➖ | `wss://hbbs.example.com:8443` | WebSocket 模式下的 ID 服务器**完整地址**（含端口/路径）。设置页"Use WebSocket"开关打开时启用，自定义端口不会被上游改写成 443。不配则 WS 开关退回上游默认行为 |
| `RD_WEBSOCKET_RELAY` | ➖ | `wss://hbbs.example.com:8444` | 同上，中继服务器的 ws 完整地址。不配则中继不随 WS 切换 |
| `RD_HIDE_NETWORK_UI` | ➖ | `false` | 是否隐藏客户端"网络设置"页（默认 `true` 隐藏）。设 `false` 则页面可见：注入的四个服务器字段仍以 ●● 只读显示、Use WebSocket 开关可用，真实值不可见不可改 |
| `RELEASE_PAT` | ➖ | fine-grained token | **仅当**用变量 `RELEASE_REPO` 把安装包发到另一个仓库时需要（该仓 Contents:read/write）。发本仓库无需此令牌 |

| Variable | 必填 | 示例 | 说明 |
|---|---|---|---|
| `RELEASE_REPO` | ➖ | `you/separate-releases` | 安装包发布目标仓，同时是每日同步检测"新版是否已发过"的依据。缺省=本仓库；仅当你要发布到别的仓库时才配置 |

> 未提供任何 `RD_*` 服务器类 Secret 时，产物为「纯行为增强版」：仅包含 UI 行为补丁，不注入任何服务器信息。

## WebSocket 模式

上游在启用 WebSocket 后会把普通域名地址改写为 `wss://域名/ws/id`（隐式 443 端口），自定义端口会丢失。本管线提供两种配合方式：

- **预置 ws 完整地址**（推荐）：配置 `RD_WEBSOCKET_ID` / `RD_WEBSOCKET_RELAY`。客户端设置页打开"Use WebSocket"后，连接自动使用你预置的完整 `ws://`/`wss://` 地址（端口与路径原样保留）；关闭开关则恢复 TCP `host:port` 直连。地址同样经 XOR 混淆注入、界面只读
- **不配置任何 WS Secret**：开关行为与上游一致（域名走 443 + `/ws/id` 路径，IP 走端口 +2 规则）

> 服务端需自行保证 ws/wss 端点可用；`wss` 证书需被客户端系统信任。

## 三种访问模式（可并存）

| 连入方式 | 被控端表现 |
|---|---|
| 内置固定密码 | 静默直连，被控机无任何窗口、任务栏零痕迹 |
| 临时随机密码（安全页查看/重置） | 同上，静默直连 |
| 无密码访客 | 隐藏的确认面板自动弹回前台请求授权；接受后正常控制；点 X 隐藏面板但会话保持 |

## 自动更新机制

- 客户端每日检查发布仓的 `releases/latest` API（默认即本仓库）
- 发现更高版本号 → 主界面弹出更新卡片，"Changelog" 链接指向上游官方对应版本的 Release 页
- 点击 Update → 从发布仓下载安装包 → 静默升级
- 版本号规则：tag 即完整版本号（CI 会写入程序内部版本）。上游小版本迭代建议加 `-N` 本地序号（如 `1.4.9-3`），上游大版本直接用其版本号（如 `1.5.0`）

## 工作流说明

| 工作流 | 触发 | 职责 |
|---|---|---|
| `upstream-sync.yml` | 每日 UTC 21:00 + 手动 | 检测上游新版 → 校验补丁（失败自动开 Issue 附冲突定位）→ 同步构建依赖 pin → **fast-check 编译门禁** → 门禁通过才派发全量构建 |
| `fast-check.yml` | 手动 / sync 门禁派发 | 复刻完整构建环境后仅跑 `cargo check`（~25 分钟），验证补丁与配置生成可编译，不打包不发布 |
| `build-windows.yml` | sync 派发 / 手动 | 完整构建 + 发布 Release（默认本仓库）；任一环节失败自动开 Issue |
| `alert` job | 上述任一作业失败 | 创建防重的失败告警 Issue |

## 故障排查（Troubleshooting）

| 症状 | 原因 | 处置 |
|---|---|---|
| `Apply custom client patches` 失败并报出编号（如 `040-cm-recall.patch`）| 上游改动触及该功能域的补丁区域，sync 已自动开 Issue 并列出冲突 hunk | 只需修复报编号的那一片：解压上游新 tag 源码 → 调整对应文件 → 重新生成该编号 patch（方法见下节）|
| `Windows cargo check`（fast-check 门禁）失败 | 补丁能贴上但编译不过（上游重构了周边代码）| 看 Issue 中的错误摘要或门禁 run 日志，修复后重跑 sync；全量构建不会启动，不浪费额度 |
| `Build rustdesk` 编译失败 | 上游升级了 Flutter/Rust/vcpkg 且自动 pin 同步未完全覆盖 | 对照上游 `flutter-build.yml@<tag>` 的 env 与步骤 diff，手工修正 build-windows.yml |
| `Publish release` 报 RELEASE_PAT（仅配置了外部 `RELEASE_REPO` 时会发生）| 令牌过期或未配置 | 重新生成并更新 Secret，然后 Re-run failed jobs；不需要外部仓就清空该变量 |
| 客户端从不提示更新 | `RD_RELEASE_REPO` 未配置或拼写错误 | 检查 Secret；确认发布仓存在对应 tag 的 Release |
| 授权框不弹出 | 确认面板唤回逻辑失效 | 检查 `main.dart` showCmWindow 是否含 `windowManager.show()`、`server_model.dart` 三处 `!client.authorized` 条件 |

## 补丁维护（上游变更后如何重新打补丁）

行为补丁按功能域拆分为**有序编号的小 patch**（不含任何个人信息，可安全公开）。sync 校验失败时会直接报出失效编号：

| 补丁文件 | 功能域 |
|---|---|
| `010-core-config-hook.patch` | `src/lib.rs` / `src/core_main.rs`：注册并在启动时调用配置注入模块 |
| `020-update-source.patch` | `src/common.rs`：更新检查重定向到你的发布仓 |
| `030-cm-window-hide.patch` | `src/ipc.rs`：无人值守模式下允许隐藏连接管理窗口 |
| `040-cm-recall.patch` | `flutter/lib/common.dart`、`models/server_model.dart`：确认事件自动唤回隐藏面板、未授权访客强制唤回 |
| `050-ui-lock.patch` | `flutter/lib/desktop/pages/server_page.dart`、`main.dart`：点 X 关闭面板不断开、隐藏态恢复可见性 |
| `060-changelog-link.patch` | `flutter/lib/desktop/pages/desktop_home_page.dart`：Changelog 链接剥离本地后缀 |
| `070-ws-address.patch` | `libs/hbb_common/src/websocket.rs`：WS 模式下优先使用预置的完整 ws 地址（`custom-rendezvous-server-ws` / `relay-server-ws`），自定义端口不被改写 |
| `080-mask-injected-fields.patch` | `flutter/lib/mobile/widgets/dialog.dart`：服务器弹窗中被注入（锁定）的字段显示为 ●● 只读，保存时提交有效值避免校验误报 |

> `src/embedded_config.rs` 不属于任何补丁——它由 CI 按 Secrets 用 `scripts/gen_embedded_config.py` 在每次构建前生成。
>
> 网络设置页可见性由 `RD_HIDE_NETWORK_UI` 控制（默认 `true` 隐藏整页；设 `false` 即不隐藏）。页面可见时："Use WebSocket" 开关可正常切换；ID/Relay/API/Key 四个注入字段即使打开也只显示 `********` 且不可编辑（补丁 080），服务器真实值不可见、不可改。

重新生成某个编号补片的流程（只动受影响的功能域）：

```bash
# A=纯净上游源码树, B=A+你修改后的源码树（只需包含该片覆盖的文件）
cd A && git init -q && git add -A && git commit -qm base
cp B/<修改过的文件> 对应路径/
git add -A && git diff --cached > patches/0NN-<name>.patch
# 验证：在全新解压的上游树按编号顺序逐个 git apply --check
```

构建与快测工作流会按文件名顺序自动循环应用 `patches/*.patch`，任一片失败即报出具体编号。

## 安全与合规声明

- 本仓库的行为补丁基于上游 RustDesk（AGPL-3.0）修改，按同许可开源，见 [LICENSE](LICENSE)；本管线的脚本与工作流同样以 AGPL-3.0 发布
- 本管线产出的安装包**未经代码签名**，首次安装 SmartScreen 会提示"仍要运行"
- 安装包二进制内必然包含连接所需的服务器信息（可被逆向提取）——这是远程客户端的工作原理所限；Secrets 只保护源码仓库与构建日志
- 内置密码 = 无人值守访问凭证，请仅部署在你有权管理的设备上；泄露后需发新版本轮换
- 上游项目采用 AGPL-3.0 许可，二次分发请遵守相应条款并保留版权声明

## 依赖与版本更新策略

| 依赖 | 更新方式 |
|---|---|
| Rust / Flutter / LLVM / vcpkg / cargo-expand / flutter_rust_bridge | 每日 sync 自动从上游 workflow 抓取并同步到 `build-windows.yml` **和** `fast-check.yml`（保持门禁与真构建工具链一致）；任何实际变更会写入运行摘要并自动开复核 Issue |
| `BRIDGE_FLUTTER_VERSION`（bridge 生成专用）、`TOPMOST_COMMIT_ID` | 无上游对应源，手动维护；上游大版本升级后若 bridge 代码生成失败再调整 |
| vcpkg 包清单 | 随上游源码树自带（检出的 tag 内 `vcpkg.json`），无需维护 |
| Flutter engine 定制版 | 固定拉取 `rustdesk/engine` 的 main 构建产物，随上游自动跟进 |
| 上游源码版本 | 每日 sync 检测新版 → 补丁校验 → fast 门禁 → 自动重建发布 |

## 成本

Public 仓库 Actions 免费无限。本模板按 Public 使用设计；若保持 Private，Windows 作业按 2× 计费率消耗额度（单次全流程约 150–190 分钟）。
