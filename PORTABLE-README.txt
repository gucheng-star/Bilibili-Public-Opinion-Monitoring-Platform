B站舆论监测平台（Windows x64 单 EXE 便携版）

当前版本
2.0.0-beta.1

如何使用
1. 从项目 GitHub Releases 下载 BiliOpinionMonitor-版本-windows-x64.exe。
2. 将 EXE 放到有写权限的目录，例如 F:\Apps\BiliOpinionMonitor。
3. 双击 EXE 即可使用，无需安装 Python、Node.js、Rust，也无需保留额外程序文件。
4. 首次启动会在 EXE 同级自动创建 data 目录，并释放经过版本和 SHA-256 校验的本地后端。
5. 首次启动可能比后续启动稍慢，请等待应用窗口出现，不需要打开命令行。

扫码登录
- 登录二维码由本机后端直接生成 PNG，不依赖第三方二维码网站。
- 一次性登录地址不会发送给第三方二维码服务。
- 扫码状态 key 放在本机 POST 请求体中，不写入本地访问日志 URL。
- Cookie 仅用于从当前电脑访问 B站接口。

数据与隐私
- 评论抓取请求直接从本机发出，因此 B站看到的是当前使用者的网络 IP 和登录 Cookie。
- SQLite 数据库、Cookie、模型设置、日志和分析记录均保存在 EXE 同级 data 目录。
- Cookie 和模型 API Key 使用当前 Windows 用户的 DPAPI 加密。
- 项目不需要 Vercel 或其他远程应用服务器参与抓取和分析。
- 删除运行时后端文件不会损坏主程序，下次启动会自动恢复。
- 删除 data 会永久丢失本机记录。需要保留数据时，请备份整个 data 目录。

移动与复制
- 只发送程序时，只需要发送 EXE。
- 同时迁移历史记录时，将 EXE 和 data 一起复制。
- 复制到另一台电脑或其他 Windows 用户后，历史数据库仍可读取，但 Cookie 和 API Key 需要重新登录或输入。

在线更新
- 应用启动后会检查 GitHub 便携版更新，也可以在设置中手动检查。
- 只有在用户确认后才会下载和安装。
- 更新包会验证 HTTPS 来源、文件大小、SHA-256、Ed25519 签名和 EXE 文件头。
- 更新只替换当前主 EXE，绝不覆盖 data 或同目录其他文件。
- 有抓取或分析任务时，程序会阻止立即安装更新。
- 新版本启动失败或健康检查超时会自动回滚旧版本。

系统要求
- Windows 10 1803（17134）或更高版本，64 位。
- Microsoft Edge WebView2 Runtime。多数 Windows 10/11 已自带。
- 如果提示缺少 WebView2，请安装 Microsoft Edge WebView2 Evergreen Runtime：
  https://developer.microsoft.com/microsoft-edge/webview2/

安全提示
- 测试版可能未进行商业代码签名，Windows SmartScreen 可能显示警告。
- 请只从本项目官方 GitHub Releases 下载。
- 下载后核对发布页提供的 SHA-256。
- 不要从陌生来源运行名称相同的 EXE。

项目地址
https://github.com/gucheng-star/Bilibili-Public-Opinion-Monitoring-Platform

版权与许可证
Copyright (c) 2026 gucheng
MIT License，英文正文和中文参考译文见仓库 LICENSE。
