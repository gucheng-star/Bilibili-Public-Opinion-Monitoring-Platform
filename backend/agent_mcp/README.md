# Agent MCP 内部集成预览

这是阶段 A 的本地技术校验，不是已发布功能。它只提供 3 个 `stdio` 工具：列出已完成分析、读取单条分析概览、检索有限评论证据。

## 安全边界

- 只接受环境变量 `BILI_MCP_DB_PATH` 指向的、已由操作者确认且停止变化的 SQLite 数据库副本。路径必须是绝对本地普通文件；拒绝相对路径、UNC/设备路径、远程盘、reparse point、WAL/SHM/journal 输入以及仍伴有这些 sidecar 的数据库。
- 数据库以 `mode=ro&immutable=1` 打开，同时启用 `query_only` 和列级 SQLite authorizer。
- 工具不会返回用户名、评论 ID、父子评论 ID、错误详情、封面路径、Cookie、密钥或本地令牌；只在进程内读取父子关系是否存在并输出布尔值。
- 不启动 FastAPI、不监听端口、不抓取评论、不调用模型、不运行迁移。内部预览组件已内嵌到 Tauri 主程序，可通过主 EXE 的 `--mcp-stdio` 模式启动；当前仍没有自动快照或面向普通用户的公开配置说明。

不要把正在写入且仍依赖 WAL 的原始数据库直接配置给此 PoC。`immutable=1` 只适用于经过确认的静态副本。

## 开发运行

在 `backend` 目录执行：

```powershell
.\venv\Scripts\python.exe -m pip install -r .\requirements-agent-mcp.txt
$env:BILI_MCP_DB_PATH = 'D:\path\to\approved-copy\data.db'
.\venv\Scripts\python.exe .\agent_mcp\server.py
```

客户端配置模板见 `client-config.example.json`。模板只包含占位路径，不得加入 Cookie、API Key、桌面本地令牌或二维码 key。

完成 Tauri 构建后，客户端应直接配置版本化主 EXE，而不是旁置的内部组件：

```powershell
$env:BILI_MCP_DB_PATH = 'D:\path\to\approved-copy\data.db'
& 'D:\path\to\BiliOpinionMonitor-<version>-windows-x64.exe' --mcp-stdio
```

无参数启动仍进入现有 GUI；`--mcp-stdio` 在创建 WebView、托盘或 HTTP 后端之前完成模式分流。

## 内部 onefile 构建

`requirements-agent-mcp-runtime.txt` 只包含产品组件运行所需的 MCP SDK；`requirements-agent-mcp-build.txt` 在此基础上固定 PyInstaller。Inspector 仅用于开发验收，不属于产品运行依赖。

```powershell
.\venv\Scripts\python.exe -m pip install -r .\requirements-agent-mcp-build.txt
.\build_agent_mcp.ps1
```

脚本每次删除专用的 `dist-agent-mcp/` 旧输出，生成 console onefile `BiliOpinionAgentMcp.exe`，验证生成时间和 SHA-256 后复制到 `frontend/src-tauri/resources/`。它不构建 Tauri 主 EXE，也不创建数据库快照。

## 验证

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_mcp -v
```

完整后端回归仍按仓库基线运行。Inspector 发现与真实副本核对记录保存在本机内部文档 `.agents/docs/AGENT_MCP_POC.md`。
