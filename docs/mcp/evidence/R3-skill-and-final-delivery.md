# R3 验收证据：Skill、配套包与最终 EXE

日期：2026-09-10
分支：`codex/agent-mcp-readonly-snapshots`
范围：只读 MCP 的公开接入资料、`bili-opinion` Skill、可重建配套包和最终 EXE 集成；不含 B 阶段写入、抓取、自动化、发布或推送。

## 已交付资料

- 公开 Skill：`skills/bili-opinion/`，包含短入口、接入、工作流、排错和 3 个代表性评测提示；Skill 明确仅覆盖应用 `0.2.4`、MCP 输出契约 v2 的已实现只读能力。
- 用户入口：`docs/mcp/README.md`；维护者契约继续位于 `docs/mcp/contract.md`。二者区分“安装 Skill”“注册 MCP”“initialize / tools/list”“实际工具调用”。
- 可重建组装：`scripts/package-agent-skill.ps1 -Version 0.2.4`。产物只包含 7 份 Skill/接入资料和包内 `manifest.json`，不包含数据库、用户配置或秘密。

## 产物与完整性

| 产物 | 本次实测值 |
| --- | --- |
| 配套包 | `dist/agent-skill/bili-opinion-skill-0.2.4.zip` |
| 配套包内容 | 8 个条目（7 个来源文件 + `manifest.json`） |
| 配套包 SHA-256 | `1034987c7bb1ae3037eef136669ad7e88176c686786982728abaa71fe47209de`（连续两次同输入组装一致） |
| 最终 EXE | `dist/portable/BiliOpinionMonitor-0.2.4-windows-x64.exe` |
| 最终 EXE 大小 | `156315136` bytes |
| 最终 EXE SHA-256 | `b36cc1c11de9f5f66289709b6e3a867d6d41987961199921f49994a840a91cac` |

## 已运行命令与结果

| 工作目录 | 命令 | 结果 | 证据 |
| --- | --- | ---: | --- |
| 仓库根目录 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\package-agent-skill.ps1 -Version 0.2.4` | 0 | 输出 package、manifest 与 SHA-256；随后以 ZipArchive 检查 8 个条目和 manifest 的 7 个来源记录。 |
| `frontend` | `powershell -NoProfile -ExecutionPolicy Bypass -File .\\build-tauri-portable.ps1` | 0 | 重建后端、嵌入式 MCP 与 Tauri 主程序。 |
| `frontend` | `powershell -NoProfile -ExecutionPolicy Bypass -File ..\\scripts\\assemble-portable.ps1 -Version 0.2.4` | 0 | 复制并校验版本化单 EXE。 |
| 仓库根目录 | `backend\\venv\\Scripts\\python.exe scripts\\smoke-final-mcp.py dist\\portable\\BiliOpinionMonitor-0.2.4-windows-x64.exe` | 0 | 2 个并发会话、7 个工具、14 次各类调用均通过；`active_directories=2`、`residual_directories=0`、`sidecars=0`。 |
| 仓库根目录 | `codex exec --ephemeral --ignore-user-config --json -s read-only -c <临时 MCP 配置>`，无仓库 Skill 镜像 | 工具均完成 | Codex CLI `0.153.4` 以本次最终 EXE 启动 stdio 服务，完成数据源、单视频发现和 NLP 概览。 |
| 仓库根目录 | `codex exec --ephemeral --ignore-user-config --json -s read-only -c <临时 MCP 配置>`，`$bili-opinion` | 工具均完成 | Codex CLI 发现与公开入口 SHA-256 一致的仓库作用域 Skill 镜像，完成数据源、事件发现、NLP 事件概览和事件证据检索。 |

## 八个场景与调用轨迹

下表的 fixture 与调用均使用隔离数据库，不使用真实用户快照。第 1–4 项为本次最终 EXE 的实际 stdio 客户端调用；第 5–8 项由相应回归用例覆盖。Python MCP Client 是协议客户端，不应被表述为 Codex 真实客户端验收。

| 场景 | 轨迹 | 结果 |
| --- | --- | --- |
| 1. 未安装 Skill 的基础发现 | `initialize → tools/list → bili_get_data_source_info → bili_list_analyses` | 最终 EXE smoke 通过，工具数为 7。 |
| 2. 单视频研判 | `bili_get_analysis_overview(analysis_id=1, nlp)` | 最终 EXE smoke 通过，情绪分母为 2。 |
| 3. 事件发现与对比入口 | `bili_list_events → bili_get_event_overview(event_id=1, nlp)` | 最终 EXE smoke 通过，事件情绪分母为 2。 |
| 4. 有限评论证据检索 | `bili_search_comments`、`bili_search_event_comments`，均为 `limit=1` | 最终 EXE smoke 通过，两类检索均返回 1 条。 |
| 5. 空数据/缺失事件 Schema | `bili_get_data_source_info` 后读取事件能力 | `tests.test_agent_mcp.ReadOnlyServiceTests.test_data_source_empty_result_and_missing_event_schema_are_explicit` 通过。 |
| 6. 快照未知或不匹配 | 读取手工副本/非匹配信任锚目录 | `tests.test_agent_snapshots.AgentSnapshotServiceTests.test_snapshot_layout_is_unknown_without_matching_shell_trust_anchor` 通过；返回 unknown，不伪造时间。 |
| 7. LLM 标签缺失 | 请求 LLM 口径的单视频与事件概览 | `test_llm_mode_requires_all_labels_and_never_triggers_analysis`、`test_event_queries_keep_source_denominators_and_partial_llm_coverage_explicit` 通过；不回退或触发模型。 |
| 8. 评论内提示注入 | 有提示注入文本的 fixture 上事件评论检索 | `test_event_comment_search_is_bounded_scoped_and_preserves_untrusted_text_as_data` 通过；内容仅作数据返回、长度受限。 |

## 真实 Codex 客户端轨迹

真实客户端为 Codex CLI `0.153.4`。两个最终会话均使用 `--ephemeral --ignore-user-config`，并只以命令行 `-c` 提供临时 MCP 条目，因此没有加载、创建、覆盖或删除用户 `config.toml`。数据库是隔离 fixture，路径含空格和中文，未使用用户快照。客户端能够初始化并发现该 stdio MCP（模型得到 7 个可用工具），每次 `mcp_tool_call` 均为 `status=completed` 且没有工具错误。

| 运行方式 | 实际工具轨迹 | 关键结果 |
| --- | --- | --- |
| 无 Skill 基线 | 临时仓库 Skill 镜像已移除，且提示未包含 `$bili-opinion`；`bili_get_data_source_info → bili_list_analyses(limit=1) → bili_get_analysis_overview(analysis_id=1, mode=nlp)` | 契约 v2、发现 7 工具、`snapshot_time_source=unknown`、情绪分母 2。 |
| 显式加载 `bili-opinion` Skill | 先将公开 `skills/bili-opinion/SKILL.md` 的 SHA-256 一致副本临时放入官方仓库作用域 `.agents/skills/bili-opinion/`，以 `$bili-opinion` 触发；`bili_get_data_source_info → bili_list_events(limit=1) → bili_get_event_overview(event_id=1, mode=nlp) → bili_search_event_comments(event_id=1, limit=1)` | Codex 明确确认正在使用该 Skill；契约 v2、发现 7 工具、事件情绪分母 2、证据返回 1 条。测试后已删除镜像文件。 |

Skill 路径中的调用顺序与实际轨迹一致：先数据源和 ID，再概览，最后小分页证据。该验收不等同于替用户永久配置客户端；用户日常使用仍应通过设置页复制出的条目手动合并配置。

## 阶段状态

R3 的实现、配套包、最终 EXE stdio 集成及真实 Codex 客户端的 Skill 加载/未加载调用验收均已完成并有证据。首轮在此停止：不发布、不推送、不进入 B 阶段。
