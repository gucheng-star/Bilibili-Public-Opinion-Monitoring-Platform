# Windows 便携桌面架构

本文档是桌面版本的跨模块契约。桌面版本采用 Tauri v2 外壳、React 静态前端和
PyInstaller `onedir` Python 后端，目标平台为 Windows 10 1803+ / Windows 11 x64。

## 边界与目标

- 抓取、情绪分析、SQLite 数据库、Cookie 和模型配置均在用户电脑上运行和保存。
- B 站请求由本机 Python 后端直接发出，因此使用用户当前网络的出口 IP 和本机 Cookie。
- Vercel 不参与应用运行；未来如需官网，仅用于展示和下载引导。
- 首个版本只发布 GitHub Release 便携 ZIP，不生成 MSI、NSIS 或 ARM64 包。
- 普通浏览器开发模式继续可用，不要求开发者必须通过 Tauri 调试前端。

## 便携目录

```text
BiliOpinionMonitor.exe
BiliOpinionUpdater.exe
backend/
data/
portable.ini
README.txt
LICENSE
```

应用拥有的所有可写数据必须位于程序目录下的 `data/`：

```text
data/database.sqlite3
data/auth.json
data/settings.json
data/logs/
data/webview/
data/update-cache/
data/update-runner/
```

程序启动时必须检查程序目录可写。只允许 Windows、WebView2 和系统组件维护自己的系统级
缓存；应用自身不得主动把数据库、Cookie、设置或更新包写入 C 盘用户目录。

## 后端启动协议

桌面外壳生成随机 256 位本地令牌并启动相邻的
`backend/BiliOpinionBackend.exe`。外壳通过以下环境变量传递运行参数：

| 变量 | 含义 |
| --- | --- |
| `BILI_DESKTOP_MODE` | 值为 `1` 时启用桌面安全模式 |
| `BILI_DATA_DIR` | 便携 `data/` 的绝对路径 |
| `BILI_DB_PATH` | SQLite 文件绝对路径 |
| `BILI_AUTH_PATH` | 登录信息文件绝对路径 |
| `BILI_SETTINGS_PATH` | 模型设置文件绝对路径 |
| `BILI_LOCAL_TOKEN` | 当前进程生命周期内的随机令牌 |
| `BILI_HANDSHAKE_PATH` | 后端原子写入的握手文件绝对路径 |

桌面后端必须绑定 `127.0.0.1:0`，由操作系统分配空闲端口。监听成功后原子写入：

```json
{
  "schema": 1,
  "port": 49152,
  "pid": 12345,
  "version": "2.0.0-beta.1"
}
```

外壳等待握手及健康检查成功后才显示主窗口。除启动探针外，桌面模式的 `/api` 请求必须
携带 `X-Bili-Local-Token`。后端只接受 Tauri 生产源 `http://tauri.localhost`，以及开发源
`http://localhost:5173`、`http://127.0.0.1:5173`，不得使用通配 CORS。

## 前端运行协议

浏览器开发模式继续使用相对地址 `/api`。桌面模式通过 Tauri command
`runtime_config` 获取：

```ts
interface RuntimeConfig {
  apiBase: string;
  localToken: string;
  appVersion: string;
}
```

所有业务请求必须经过统一 API 客户端。桌面客户端将 `apiBase` 作为前缀，并自动加入本地
令牌；组件不得直接请求 `/api/...`。`/china.json` 等前端静态资源不属于此限制。

## 生命周期协议

后端提供：

- `GET /api/runtime/health`：返回后端版本和就绪状态。
- `GET /api/runtime/activity`：返回当前长任务数量和可安全退出状态。
- `POST /api/runtime/prepare-exit`：请求停止可取消任务并准备退出。

空闲时关闭窗口直接退出。存在任务时显示三项选择：

1. 停止任务并退出；
2. 继续在托盘运行；
3. 取消关闭。

系统托盘至少提供“显示主窗口”和“退出”。主进程退出或异常终止时，应通过 Windows Job
Object 或等效机制结束后端进程。

## 本地秘密

Cookie 和每项 LLM 的 API Key 使用当前 Windows 用户的 DPAPI 加密，持久化格式为
`enc:v1:<base64>`。读取旧明文时应原子迁移。把整个目录复制到另一台电脑时：

- 数据库和历史记录仍可打开；
- 无法解密的 Cookie 要求重新扫码登录；
- 无法解密的 API Key 要求重新输入；
- 任何解密失败都不得删除数据库或覆盖历史数据。

## 便携更新协议

应用启动约五秒后检查 GitHub Release，也允许在设置中手动检查。检查到新版本后必须先由
用户确认，运行中的长任务会阻止立即安装。

`latest-portable.json` 至少包含：

```json
{
  "schema": 1,
  "version": "2.0.0-beta.2",
  "published_at": "2026-08-08T00:00:00Z",
  "notes_url": "https://github.com/.../releases/tag/v2.0.0-beta.2",
  "minimum_windows": "10.0.17134",
  "asset": {
    "name": "BiliOpinionMonitor-2.0.0-beta.2-windows-x64.zip",
    "url": "https://github.com/.../download/...zip",
    "size": 123,
    "sha256": "..."
  },
  "signature": "..."
}
```

Ed25519 签名文本固定为：

```text
schema|version|asset.name|asset.size|asset.sha256
```

更新器必须验证 HTTPS 来源、大小、SHA-256、Ed25519 签名和 ZIP 路径安全；只能替换程序
文件，永远不得覆盖 `data/` 或 `portable.ini`。替换前保留可回滚副本，更新后等待最多
60 秒健康标记，失败则恢复旧版本。签名私钥只存在于 GitHub Actions Secret，仓库和发布包
内只放公钥。

## 发布门禁

发布工作流只能由 `v*` 标签触发，并依次完成：后端单元测试、前端 lint/build、Rust
fmt/test/build、Python `onedir` 构建、便携目录组装、ZIP 校验、manifest 签名与 GitHub
Release 上传。创建标签、推送分支或发布 Release 均需项目所有者单独确认。
