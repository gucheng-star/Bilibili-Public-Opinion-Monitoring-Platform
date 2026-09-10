# 连接与快照更新

## 连接前

1. 确认桌面应用已经完成 B 站登录和至少一次本地分析；本地引导只会基于已有数据创建一致快照，不抓取或分析新内容。
2. 该数据库是本地敏感文件：不要上传、不要提交 Git、不要把整个 `data/` 目录交给模型。
3. 只使用已验证的桌面主 EXE、固定的 `--mcp-stdio` 和接入记录中的 `BILI_MCP_DB_PATH`。不要传入前端 Token、Cookie 或 API Key。

## 让 Agent 协助注册（推荐）

`SKILL.md` 已包含一行远程读取后的首次接入流程；本参考只补充仓库或配套包可用时的详细步骤。用户把下列授权发送给**本机 Codex Agent**；Agent 负责调用桌面程序本地引导、读取应用目录中的接入记录并注册，不要求用户寻找设置页或复制 JSON：

```text
请读取 `bili-opinion` Skill；若无法读取则停止并要求我提供，不得注册。我明确授权你调用已安装桌面程序的本地引导创建只读快照，并仅新增或更新本机 Codex 的 `bili-opinion-readonly`：先备份并严格校验引导 JSON，绝不改其他 MCP、上传数据库或密钥；重连后验证 `tools/list` 与 `bili_get_data_source_info`，再按 Skill 进行只读研判。
```

此授权只覆盖该条目：Agent 必须以结构化参数运行已验证的主 EXE 的 `--mcp-bootstrap`，确认其成功退出后只读取该 EXE 同级 `data/agent-snapshots/latest-bootstrap.json`，而不是猜测路径、暗中读取剪贴板或扫描用户所有文件。应用会在内部以一次性 nonce 验证记录的新鲜度；Agent 仍须拒绝任何不满足以下条件的记录：`schema` 为 `1`；快照数据库和清单同属该 EXE 同级的 `data/agent-snapshots/<snapshot-id>/`；数据库为存在的绝对 `.sqlite3`。Agent 用已验证 EXE、精确的 `["--mcp-stdio"]` 和这个数据库路径构造唯一条目。通过校验后，先以 `codex mcp get bili-opinion-readonly --json` 检查现有条目，随后通过 `codex mcp add bili-opinion-readonly --env BILI_MCP_DB_PATH=<接入记录中的路径> -- <已验证主EXE路径> --mcp-stdio` 注册。若同名条目不同，只有提示中包含“新增或更新”时，才可在备份后先执行 `codex mcp remove bili-opinion-readonly`、再替换这一个条目。当前会话未出现工具时需要新开或重新连接，不能靠修改其他 MCP 配置解决。

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

- 新数据不会写入旧快照。再次明确授权 Agent 运行 `--mcp-bootstrap`，它会更新 `BILI_MCP_DB_PATH` 并重新连接；旧会话继续读取旧快照。
- 应用升级后 EXE 文件名可能变化。再次明确授权 Agent 运行本地引导，并更新 `command` 后重新连接。
- 卸载时仅删除本服务条目；不要删除其他 MCP 服务。确认没有会话使用后再由用户决定是否删除旧快照目录。
