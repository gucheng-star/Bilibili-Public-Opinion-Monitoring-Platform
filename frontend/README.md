# 前端开发说明

本目录包含 B站舆论监测平台的 React 19 + TypeScript + Vite 界面，以及 Windows Tauri v2 桌面外壳。

项目总览、普通用户说明和 GitHub 发布门禁见根目录 [README.md](../README.md)。桌面跨模块契约见 [docs/DESKTOP_ARCHITECTURE.md](../docs/DESKTOP_ARCHITECTURE.md)。

## 环境要求

- Node.js 22+
- pnpm 11
- 后端 Python 3.12 虚拟环境 `../backend/venv`
- Rust 1.77+，仅 Tauri 开发和构建需要

## 安装

```powershell
cd frontend
pnpm install
```

本项目只使用 pnpm。不要用 npm 或 yarn 重写锁文件。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `pnpm run dev` | 启动 Vite 开发服务器 |
| `pnpm run lint` | 运行 Oxlint |
| `pnpm run build` | TypeScript 检查并构建前端 |
| `pnpm run tauri:dev` | 启动 Tauri 开发模式 |
| `pnpm run tauri:build` | 重建 Python 后端并构建 Tauri 单 EXE 主程序 |

## 浏览器开发模式

先启动后端：

```powershell
cd ..\backend
.\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

再启动前端：

```powershell
cd ..\frontend
pnpm run dev
```

打开 `http://localhost:5173`。Vite 将 `/api` 代理到 `127.0.0.1:8000`。

前端使用 `HashRouter`：工作台为 `#/`，独立设置页为 `#/settings`。Hash 路由保证浏览器开发模式和从 `index.html` 启动的 Tauri WebView 都能直接刷新当前页面。

## 浏览器与桌面两种运行时

`src/services/api.ts` 是唯一业务 API 入口：

- 浏览器模式使用相对路径 `/api`。
- 桌面模式由 `src/services/desktop.ts` 调用 Tauri `runtime_config`，获取动态 `apiBase` 和 `localToken`。
- 桌面请求自动加入 `X-Bili-Local-Token`。
- React 组件不得直接请求 `/api/...`。
- `/china.json` 等打包静态资源不属于业务 API。

## 扫码登录约束

- `GET /api/auth/qrcode` 返回本机生成的 `image_data_url` 和短期 `qrcode_key`。
- 前端只接受 PNG data URL，不拼接或请求第三方二维码图片地址。
- 状态轮询使用 `POST /api/auth/qrcode/status` 和 JSON body。
- 重试、返回和卸载组件时，旧轮询必须失效。
- 成功、过期、网络失败、保存失败和图片加载失败都必须有可见状态。
- 已保存账号使用后端返回的稳定 `index`；切换失败时保留登录页并显示可操作提示。

Tauri CSP 中 `img-src` 必须保留 `data:`，不得为二维码加入 `api.qrserver.com`。

## 关键目录

```text
src/
├── App.tsx                    # 应用路由、共享状态、分析轮询、筛选和桌面关闭流程
├── pages/SettingsPage.tsx     # 独立模型、抓取和更新设置页
├── components/               # 导航、登录、设置、筛选、图表和评论组件
├── services/api.ts           # 统一 API 客户端
├── services/desktop.ts       # Tauri command bridge
└── types/                    # API 与 UI 类型

src-tauri/
├── src/main.rs               # 桌面生命周期、托盘、内嵌后端和 commands
├── src/portable.rs           # 便携路径、版本和更新清单
├── src/bin/updater.rs        # 内置更新 runner
├── tauri.conf.json           # 窗口、安全策略和版本
└── Cargo.toml                # Rust 包版本与依赖
```

## UI 约束

- 所有用户界面文字使用中文。
- 样式使用纯 CSS 和 CSS 变量双主题，不引入 Tailwind。
- ECharts 在主题变化时需要重挂载或重绘。
- 桌面使用多列等宽布局，移动端切换为单列。
- 图表隐藏数量为 0 的分类，相关规则应同步应用到情感和性别图。
- NLP/LLM 模式切换时，图表、筛选和评论表格标签必须一致。
- 工作台和设置使用应用内路由切换；返回工作台不得清空当前分析与筛选状态。
- 评论抓取和 LLM 重分析共用同一套进度仪表；LLM 进度必须留在情感分布卡片中，并使用后端实际完成数量，不能用评论总数模拟进度。
- 日期弹层不得覆盖顶部 sticky 输入区域。
- 动画支持 `prefers-reduced-motion`。

## 验证

```powershell
pnpm run lint
pnpm run build
```

登录、主题、筛选、图表或桌面桥接变更还需要真实浏览器验收。二维码至少检查：

- 图片 `naturalWidth > 0`。
- `src` 以 `data:image/png;base64,` 开头。
- 网络记录中没有 `api.qrserver.com`。
- `/auth/qrcode/status` URL 中没有 `qrcode_key`。
- 浏览器控制台没有 CSP 或资源错误。

桌面关键改动必须重建最终 EXE，并在真实 WebView 中重复验收。

## 单 EXE 构建

```powershell
pnpm run tauri:build

cd ..
.\scripts\assemble-portable.ps1 -Version 2.0.0-beta.1
```

`tauri:build` 会先调用后端构建脚本，并校验刚生成的 Python onefile 与 `src-tauri/resources/BiliOpinionBackend.exe` 哈希一致。不要手工跳过此步骤。
