# rustdesk-custom

RustDesk 定制客户端构建管线（源码私有，Releases 公开）。

- **本仓库（私有）**：补丁 + CI 工作流
- **[kumu7y/rustdesk-release](https://github.com/kumu7y/rustdesk-release)（公开）**：安装包 Releases

## 它做什么

1. `upstream-sync.yml` 每日检查 [rustdesk/rustdesk](https://github.com/rustdesk/rustdesk) 最新 Release
2. 发现新版本 → 校验 `patches/custom-client.patch` 能否干净应用 → 触发 `build-windows.yml`
3. 构建基于上游对应 tag 的源码 + 我们的补丁 → Windows x64 安装包（exe 自解压版 + msi）
4. 构建产物自动发布到公开仓库 `kumu7y/rustdesk-release`
5. 已安装的定制客户端每日检查该仓库的 `releases/latest`，发现新版后弹窗提示，用户点击下载并静默升级

## 补丁内容（patches/custom-client.patch）

| 文件 | 改动 |
|---|---|
| `src/embedded_config.rs`（新增） | 服务器配置 XOR 混淆 + 强制覆盖层注入；内置 UI 隐藏开关（hide-network-settings 等）；内置密码哈希；更新检查指向的发布仓库名 |
| `src/lib.rs` | 注册新模块 |
| `src/core_main.rs` | 启动时注入服务器配置 |
| `src/common.rs` | 软件更新检查改为查询 `api.github.com/repos/kumu7y/rustdesk-release/releases/latest` |

> 注：混淆仅防随手扫描（`strings` 等），安装包公开分发决定了连接信息必然存在于二进制内，决心逆向者仍可提取。

## 首次使用（必做）

发布步骤需要一个跨仓库 Personal Access Token：

1. GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token
   - Repository access: *Only select repositories* → 选 `rustdesk-release`
   - Permissions: **Contents: Read and write**
2. 本仓库 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `RELEASE_PAT`，Value: 上一步的 token

没有这个 Secret 时，构建会成功但发布步骤报错提醒。

## 手动触发一次构建

Actions → Build Windows Custom Client → Run workflow → 输入 tag（如 `1.4.9`）。

或直接触发同步检查：Actions → Upstream Sync → Run workflow。

## 维护补丁

上游改动触及补丁覆盖的代码路径时，`Upstream Sync` 会开 issue 提醒。重新生成补丁：

```bash
# 1. 解压上游对应 tag 源码到 A/ 与 B/ 两份目录
# 2. 在 B/ 中修改文件（参考下表）
# 3. 生成补丁：
cd A && git init -q && git add -A && git -c user.name=p -c user.email=p@l commit -qm base
cp B/src/*.rs 修改过的文件 → A/src/
cd A && git add -A && git diff --cached > patches/custom-client.patch
# 4. 验证：在全新解压的上游树中 git apply --check patches/custom-client.patch
```

## 成本（私有仓库 Actions 分钟数）

Windows runner 按 2 倍计费。单次全流程约 150–190 计费分钟；免费额度 2000 分钟/月，足够支撑上游每月 1–2 次发版 + 重试。

## 注意事项

- 构建产物**未做代码签名**，首次安装时 SmartScreen 会提示"更多信息 → 仍要运行"
- 公开仓库中的安装包含内嵌的服务器域名与**公钥**（泄露无害），但请勿把私钥类信息放进补丁
- 客户端"检查更新"依赖 GitHub 网络可达性；如日后需要迁移到自托管更新端点，只需修改 `embedded_config.rs` 中常量并重新生成补丁
