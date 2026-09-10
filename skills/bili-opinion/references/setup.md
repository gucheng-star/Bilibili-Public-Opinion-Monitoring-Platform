# 连接与快照更新

## 连接前

1. 在桌面应用“设置 → Agent / MCP”中点击“生成 Agent 快照”。记下页面显示的主 EXE 路径和 `database.sqlite3` 路径。
2. 该数据库是本地敏感文件：不要上传、不要提交 Git、不要把整个 `data/` 目录交给模型。
3. 只使用页面给出的版本化主 EXE 路径、`--mcp-stdio` 和 `BILI_MCP_DB_PATH`。不要传入前端 Token、Cookie 或 API Key。

## 让 Agent 协助注册（推荐）

`SKILL.md` 已包含一行远程读取后的首次接入流程；本参考只补充仓库或配套包可用时的详细步骤。用户在桌面应用“设置 → Agent / MCP”生成快照并点击“复制 JSON 配置”，再把下列一行和完整 JSON 一起发送给**本机 Codex Agent**：

```text
请读取 `bili-opinion` Skill；若无法读取则停止并要求我提供，不得注册。现在我明确授权你把下方“复制 JSON 配置”注册到本机 Codex：仅新增或更新 `bili-opinion-readonly`，先做本地配置备份并严格校验 JSON，绝不改其他 MCP、上传数据库或密钥；重连后验证 `tools/list` 与 `bili_get_data_source_info`，再按 Skill 进行只读研判。JSON：<在此粘贴完整 JSON>
```

此授权只覆盖该条目：Agent 应解析用户粘贴的 JSON，而不是猜测路径或暗中读取剪贴板。写入前必须拒绝任何不满足以下条件的输入：仅有 `mcpServers.bili-opinion-readonly` 条目；`command` 是存在的绝对 `.exe` 路径；`args` 精确为 `["--mcp-stdio"]`；`env` 仅含指向存在的绝对 `.sqlite3` 路径的 `BILI_MCP_DB_PATH`。通过校验后，先以 `codex mcp get bili-opinion-readonly --json` 检查现有条目，随后通过 `codex mcp add bili-opinion-readonly --env BILI_MCP_DB_PATH=<JSON中的路径> -- <JSON中的主EXE路径> --mcp-stdio` 注册。若同名条目不同，只有提示中包含“新增或更新”时，才可在备份后先执行 `codex mcp remove bili-opinion-readonly`、再替换这一个条目。当前会话未出现工具时需要新开或重新连接，不能靠修改其他 MCP 配置解决。

桌面应用不参与写入客户端配置；它只生成一致快照和 JSON。该流程只适用于本机 Codex 配置，不能用于 ChatGPT 网页版，也不允许把 JSON、备份或数据库发给远端模型。

## Codex 手动注册（备选）

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
