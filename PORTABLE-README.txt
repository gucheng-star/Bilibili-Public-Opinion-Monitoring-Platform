B站舆论监测平台（Windows x64 便携版）

使用方式
1. 将下载的 BiliOpinionMonitor-版本-windows-x64.exe 放到可写目录，例如 F:\Apps\BiliOpinionMonitor。
2. 双击 EXE 即可使用；无需安装，也没有必须保留的程序文件夹。
3. 首次启动会自动创建同级 data 目录，并从 EXE 恢复本地运行组件。

数据与隐私
- 评论抓取、Cookie、SQLite 数据库、模型配置和分析记录均保存在 EXE 同级的 data 文件夹。
- 抓取请求直接从本机发出，因此网站看到的是当前使用者的网络 IP 和登录 Cookie。
- EXE 可单独移动并重新生成程序运行文件；data 被删除会丢失本地记录，建议定期备份。
- 复制到另一台电脑时，历史数据可随 data 一同迁移；为保护安全，Cookie 和 API 密钥需要在新电脑重新输入或登录。

更新
- 启动后会检查 GitHub 便携版更新，并在您确认后下载。
- 更新只替换主 EXE，绝不覆盖 data。
- 有抓取或分析任务时，程序会阻止安装更新。

系统要求
- Windows 10 1803（17134）或更高版本，64 位。
- Microsoft Edge WebView2 Runtime。多数 Windows 10/11 已自带；如果程序无法启动或提示缺少 WebView2，请到下列微软页面安装 Evergreen Runtime：
  https://developer.microsoft.com/microsoft-edge/webview2/

首次发布为未签名版本，Windows SmartScreen 可能显示警告。请只从本项目 GitHub Releases 下载，并核对发布页提供的 SHA-256。
