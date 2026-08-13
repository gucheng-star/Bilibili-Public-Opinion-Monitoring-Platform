# Windows 便携桌面架构

本文档是桌面版本的跨模块契约。桌面版本采用 Tauri v2 外壳、React 静态前端和
PyInstaller `onefile` Python 后端，目标平台为 Windows 10 1803+ / Windows 11 x64。

## 边界与目标

- 抓取、情绪分析、SQLite 数据库、Cookie 和模型配置均在用户电脑上运行和保存。
- B 站请求由本机 Python 后端直接发出，因此使用用户当前网络的出口 IP 和本机 Cookie。
- Vercel 不参与应用运行；未来如需官网，仅用于展示和下载引导。
- 首个版本只发布 GitHub Release 单文件便携 EXE，不生成 MSI、NSIS 或 ARM64 包。
- 普通浏览器开发模式继续可用，不要求开发者必须通过 Tauri 调试前端。

## 单文件与数据目录

```text
BiliOpinionMonitor-2.0.0-beta.1-windows-x64.exe
data/  # 首次启动自动创建，不属于发布包
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
data/runtime/BiliOpinionBackend.exe
data/runtime/tmp/
```

程序启动时必须检查程序目录可写。只允许 Windows、WebView2 和系统组件维护自己的系统级
缓存；应用自身不得主动把数据库、Cookie、设置或更新包写入 C 盘用户目录。

主 EXE 内嵌前端、Tauri 外壳、Python onefile 后端和更新 runner 代码。运行时必须把后端
按版本和 SHA-256 校验后原子释放到 `data/runtime/`；运行组件被删除时，下次启动自动恢复。
SQLite、Cookie 和设置不能写回正在运行的 EXE，因此删除 `data/` 仍会丢失用户数据。

## 后端启动协议

桌面外壳生成随机 256 位本地令牌，校验并启动从主 EXE 释放的
`data/runtime/BiliOpinionBackend.exe`。外壳通过以下环境变量传递运行参数：

| 变量 | 含义 |
| --- | --- |
| `BILI_DESKTOP_MODE` | 值为 `1` 时启用桌面安全模式 |
| `BILI_DATA_DIR` | 便携 `data/` 的绝对路径 |
| `BILI_DB_PATH` | SQLite 文件绝对路径 |
| `BILI_AUTH_PATH` | 登录信息文件绝对路径 |
| `BILI_SETTINGS_PATH` | 模型设置文件绝对路径 |
| `BILI_LOCAL_TOKEN` | 当前进程生命周期内的随机令牌 |
| `BILI_HANDSHAKE_PATH` | 后端原子写入的握手文件绝对路径 |

外壳同时把 `TEMP`、`TMP` 和 `TMPDIR` 指向 `data/runtime/tmp/`，使 PyInstaller onefile
运行时文件留在便携目录所在磁盘，不默认占用系统盘临时目录。后端使用 Windows GUI 子系统，
不得弹出命令行窗口；诊断信息写入 `data/logs/backend.log`。

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

前端使用 Hash 路由：工作台为 `#/`，设置页为 `#/settings`。Tauri 仍只加载内嵌
`index.html`，路由片段不触发文件系统子路径访问；工作台与设置切换时保留当前分析状态。

## 本地二维码协议

扫码登录不得依赖第三方二维码图片服务。后端从 B站取得授权 URL 后，必须在本机生成 PNG，
并通过 `GET /api/auth/qrcode` 返回 `data:image/png;base64,...` 格式的
`image_data_url` 和 `qrcode_key`。前端只显示该本地 data URL；Tauri CSP 允许 `data:`
图片，但不得为外部二维码域名放宽 `img-src`。

轮询使用 `POST /api/auth/qrcode/status`，请求体为：

```json
{
  "qrcode_key": "..."
}
```

这样可以避免登录键出现在本地访问日志和 URL 历史中。返回、重试、组件卸载或二维码过期时，
前端必须取消旧轮询，旧请求不得覆盖新二维码的界面状态。Cookie 只由本地后端保存，API 响应
不得返回 Cookie 内容。

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
    "name": "BiliOpinionMonitor-2.0.0-beta.2-windows-x64.exe",
    "url": "https://github.com/.../download/...exe",
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

更新器必须验证 HTTPS 来源、大小、SHA-256、Ed25519 签名和 Windows EXE 文件头。安装时
主 EXE 复制自身到 `data/update-runner/`，以内部 runner 模式等待父进程退出，只替换当前
主 EXE，永远不得覆盖 `data/` 或同目录其他文件。替换前保留可回滚副本，更新后等待最多
60 秒健康标记，失败则恢复旧版本。签名私钥只存在于 GitHub Actions Secret，仓库和发布包
内只放公钥。

## 发布门禁

发布工作流只能由 `v*` 标签触发，并依次完成：后端单元测试、前端 lint/build、Rust
fmt/test/build、Python `onefile` 构建、单 EXE 组装、manifest 签名与 GitHub
Release 上传。`frontend/build-tauri-portable.ps1` 必须先重建后端，再校验新产物与
`src-tauri/resources/BiliOpinionBackend.exe` 的 SHA-256 一致，禁止复用旧内嵌资源。

二维码、Pillow 和 PyInstaller 等影响单文件封装的依赖必须固定版本。发布前还要确认 Git
标签、`Cargo.toml` 和 `tauri.conf.json` 的版本完全一致，并用最终 EXE 验证：后端健康、
本地二维码 PNG 可生成、WebView 中二维码图片实际可见且没有 CSP 错误。创建标签、推送分支
或发布 Release 均需项目所有者单独确认。

## 相关文档

- GitHub 项目入口：[`../README.md`](../README.md)
- 项目实现说明：[`../PROJECT.md`](../PROJECT.md)
- 用户便携版说明：[`../PORTABLE-README.txt`](../PORTABLE-README.txt)
