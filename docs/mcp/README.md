# B站舆论监测只读 MCP 接入

这是一套本地 stdio 只读接口：桌面应用把用户主动生成的 SQLite 快照提供给已连接的 MCP 客户端，供模型研判已有单视频分析和多来源舆情事件。它不抓取 B站、不调用模型、不创建事件、不写数据库，也不监听网络端口。

## 最快接入：把一行提示和 JSON 交给 Agent

适用于桌面应用与 Codex 在同一台电脑上运行。先让 Agent 能读取完整的 `skills/bili-opinion/` 目录：要么在包含该目录的仓库中启动 Agent，要么把配套包中的整个目录随消息附给它。然后在桌面应用完成已有分析或事件整理，打开“设置 → Agent / MCP”，点击“生成 Agent 快照”，再点击“复制 JSON 配置”。把下方**整行**连同刚复制的 JSON 发给你的 Agent：

```text
请读取我随附的完整 `bili-opinion` Skill（或本仓库 `skills/bili-opinion/`）；若无法读取则停止并要求我提供，不得注册。现在我明确授权你把下方“复制 JSON 配置”注册到本机 Codex：仅新增或更新 `bili-opinion-readonly`，先做本地配置备份并严格校验 JSON，绝不改其他 MCP、上传数据库或密钥；重连后验证 `tools/list` 与 `bili_get_data_source_info`，再按 Skill 进行只读研判。JSON：<在此粘贴桌面应用复制的完整 JSON>
```

这句授权让 Agent 可以使用 `codex mcp add` 完成**指定服务**的本机注册；它不授权访问其他 MCP、复制完整数据库、抓取 B站或执行写入操作。若同名服务现有配置与 JSON 不一致，Agent 只能替换这一条目，并应在结果中说明发生了更新。当前会话没有自动刷新工具时，重新开启或重新连接一个 Codex 会话，再由 Agent 验证连接。

桌面应用本身始终不会自动修改、覆盖或删除任何客户端配置。ChatGPT 网页版不能读取本机 Codex 配置；本流程面向本机 Codex CLI、桌面应用或 IDE 扩展。Codex 的 stdio MCP 可用 CLI 注册，且桌面应用、CLI 和 IDE 扩展共享同一主机上的 MCP 配置；具体位置与客户端界面以[官方 MCP 文档](https://learn.chatgpt.com/zh-Hans/docs/extend/mcp)为准。

## 不使用 Agent 时

熟悉终端的用户可把设置页显示的两个实际绝对路径代入这一行，在本机执行：

```powershell
codex mcp add bili-opinion-readonly --env "BILI_MCP_DB_PATH=<设置页显示的 database.sqlite3 绝对路径>" -- "<设置页显示的主 EXE 绝对路径>" --mcp-stdio
```

随后重新连接客户端，依次验证 initialize、`tools/list` 与 `bili_get_data_source_info`。若已有同名条目，先用 `codex mcp get bili-opinion-readonly` 检查；只在确认需要更新这一个服务时处理它。完整的 Agent 注册、更新和卸载边界见[配套 Skill 的接入说明](../../skills/bili-opinion/references/setup.md)。

## 使用顺序

1. 让 Agent 先调用 `bili_get_data_source_info`，记录 `snapshot_id`、时间可信来源和限制。
2. 用 `bili_list_analyses` 或 `bili_list_events` 取得实际 ID，不能按标题猜测。
3. 调用相应概览，默认使用 `mode="nlp"`；仅在工具确认完整标签时使用 LLM 口径。
4. 只为支撑具体结论，以小分页检索有限评论证据；不要拉取整个评论库。
5. 新数据需要生成新快照、更新 `BILI_MCP_DB_PATH` 并重新连接；已运行会话继续读取旧快照。

当前契约为 v2，标准工具共 7 个：三个单视频工具、数据源信息、事件列表、事件概览和事件评论检索。完整字段、错误边界和兼容性见[维护者契约](contract.md)；推荐调用顺序与客户端配置见[配套 Skill](../../skills/bili-opinion/SKILL.md)。

## 隐私与范围

快照数据库仍是本地敏感文件，包含的评论文本并非已匿名数据库。连接外部模型时，MCP 返回的统计数据及移除工具级用户名/UID字段、长度截断的评论片段可能发送给该模型；Cookie、API Key、UID 和数据库路径不会通过工具返回。评论文本也可能含用户自行公开的敏感内容，请按业务场景审慎连接外部模型。

不要把快照数据库、`data/` 目录、用户 MCP 配置或密钥放入 Git、发布包或第三方网盘。普通手工静态副本可以查询，但其快照时间和 ID 为未知；文件 mtime 不能替代生成时间。

## 配套包与验证

仓库中的 `scripts/package-agent-skill.ps1` 只打包 Skill、用户接入说明与契约；它生成内容清单和 SHA-256，不含数据库、配置或秘密。使用说明在脚本输出的 manifest 中。最终 EXE 的完整 stdio 冒烟使用 `scripts/smoke-final-mcp.py`；它验证工具发现、所有 7 个工具调用、并发会话、临时目录回收和 fixture 不变性。
