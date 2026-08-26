# WebSocket 完整地址联动 + 网络页可见 + 注入信息掩码

## 背景（探索证实）
- 上游 `hbb_common/src/websocket.rs check_ws()`：启用 WS 后普通域名地址会**丢端口**变 `wss://域名/ws/id`（隐式 443）；而以 `ws://`/`wss://` 开头的**完整地址原样透传**，端口/路径全保留——这是实现基础
- 四个服务器键被 `OVERWRITE_SETTINGS` 锁定：UI 能读到真实值、写回被静默丢弃 → "掩码显示"在 Flutter 弹窗层做，"WS 切换"不能靠 Dart 写键、要在连接转换层读独立的 `-ws` 影子键
- `allow-websocket` 键不锁定时，设置页开关天然可交互

## 改动清单

### 1. 生成器 `scripts/gen_embedded_config.py`
- 新增可选 Secret **`RD_WEBSOCKET_ID`**（WS 开启时的 ID 服务器完整地址，如 `wss://rustdesk.kumu7y.icu:8443` 或带路径形式）、**`RD_WEBSOCKET_RELAY`**（中继 ws 形式，可省略=不切换中继）
- 非空时注入新锁定键 `custom-rendezvous-server-ws` / `relay-server-ws`（XOR 混淆同现有）
- 不注入 `allow-websocket`（留给运行期开关）
- 打印行增加 `ws_entries=N`；防回归断言照常覆盖

### 2. 新补丁 `patches/070-ws-address.patch`
目标：`libs/hbb_common/src/websocket.rs` 的 `check_ws()`（L340 起）。在透传判断之后、端口算术之前插入：
```rust
// Custom client: a configured full ws-form address replaces the plain
// host:port verbatim, so custom ports survive websocket mode.
let ws_id = Config::get_option("custom-rendezvous-server-ws");
if !ws_id.is_empty() {
    let id = Config::get_rendezvous_server();
    if !id.is_empty() && endpoint.starts_with(&host_part(&id)) { return ws_id; }
}
// relay-server-ws 同理（对照 relay-server 选项的 host 匹配）
```
（实现时以 host 部分匹配，兼容 endpoint 带端口/不带端口两种形态；辅助函数放同文件）
- 子模块文件按磁盘路径 git apply，CI `submodules: recursive` 后可行，fast-check 将实际验证

### 3. 新补丁 `patches/080-mask-injected-fields.patch`
目标：`flutter/lib/mobile/widgets/dialog.dart`（桌面"ID/Relay Server"弹窗复用此文件）
- `showServerSettingsWithValue`：四个控制器建好后，若 `isOptionFixed('custom-rendezvous-server')` 等为真且文本非空 → 文本替换为 `'●●●●●●●●'` 并标记该字段锁定
- 锁定字段的 TextField：`readOnly: true` + 灰色样式 + 提示"由管理员配置"
- `submit()`：跳过锁定键——不调用 setOption、不做 `mainTestIfValidServer` 测试（避免掩码假值触发测试失败弹窗）；未锁定的字段行为不变

### 4. 工作流 env
`build-windows.yml` 与 `fast-check.yml` 的 generate 步骤追加映射 `RD_WEBSOCKET_ID` / `RD_WEBSOCKET_RELAY`

### 5. README
- Secrets 表新增两行（示例值占位，注明"填你实际的 ws 完整地址形态"）
- 新增"WebSocket 模式"小节：开启 Use WebSocket → 连接走预置完整 ws 地址（自定义端口不被改写）；关闭 → 回 TCP `host:port`
- 补丁维护表补 070/080 两行；注明 `RD_HIDE_NETWORK_UI=false` 时页面可见、四字段为掩码只读

## 你需要做的（实施后）
创建两个新 Secrets：`RD_WEBSOCKET_ID`（必填才有 WS 切换效果）、`RD_WEBSOCKET_RELAY`（可选），值为你实际的自定义接入地址

## 验证计划
1. 本地：生成器带 WS 参数跑通 + 语法断言；纯净树按序 `git apply --check` 全部 8 个补丁
2. push → fast-check 回归绿（cargo check 会编译 hbb_common 补丁）
3. 全量构建 `1.4.9-11` 发布
4. 手工 QA：网络页可见且四字段显示 ●● 只读；开 WS 开关 → 连接走你的 ws 地址（自定义端口生效）；关 WS → 恢复 `host:port` 直连

## 风险
- 上游升级时 hbb_common 纳入 rebase 面（070 编号独立，定位容易）
- wss 自签证书需系统信任（服务端事项，与管线无关）
- 切换开关后的重连时机沿用上游行为（下次连接生效/必要时重启应用）
