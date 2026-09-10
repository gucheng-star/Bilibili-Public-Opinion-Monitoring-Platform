# 连接与快照更新

## 连接前

1. 在桌面应用“设置 → Agent / MCP”中点击“生成 Agent 快照”。记下页面显示的主 EXE 路径和 `database.sqlite3` 路径。
2. 该数据库是本地敏感文件：不要上传、不要提交 Git、不要把整个 `data/` 目录交给模型。
3. 只使用页面给出的版本化主 EXE 路径、`--mcp-stdio` 和 `BILI_MCP_DB_PATH`。不要传入前端 Token、Cookie 或 API Key。

## Codex 手动注册

不要覆盖已有 MCP 配置。可通过 Codex 的 MCP 管理界面新增一个 **stdio** 服务器，或手动将下列条目合并进用户或受信任项目的 `config.toml`；必须把两个示例路径替换为桌面应用显示的实际绝对路径。

```toml
[mcp_servers.bili-opinion-readonly]
command = "F:\\Apps\\Bili 舆情\\BiliOpinionMonitor-0.2.4-windows-x64.exe"
args = ["--mcp-stdio"]

[mcp_servers.bili-opinion-readonly.env]
BILI_MCP_DB_PATH = "F:\\Apps\\Bili 舆情\\data\\agent-snapshots\\<snapshot-id>\\database.sqlite3"
```

保存后重启或重新连接客户端。先确认 initialize 成功，再用 `tools/list` 发现 7 个只读工具，最后调用 `bili_get_data_source_info`。配置文件的位置、界面入口和状态查看以官方 OpenAI MCP 文档为准；该文档说明 Codex 使用 `[mcp_servers.<name>]` 的 stdio `command`、`args` 和 `env` 配置，并可通过 `/mcp` 查看连接状态。

## 更新与卸载

- 新数据不会写入旧快照。重新生成快照后，手动更新 `BILI_MCP_DB_PATH` 并重新连接；旧会话继续读取旧快照。
- 应用升级后 EXE 文件名可能变化。更新 `command` 为页面显示的新版本路径，再重新连接。
- 卸载时仅删除本服务条目；不要删除其他 MCP 服务。确认没有会话使用后再由用户决定是否删除旧快照目录。
