# R1 验收证据：只读事件与数据源查询

日期：2026-09-09
分支：`codex/agent-mcp-readonly-snapshots`
范围：新增静态 SQLite 的只读事件发现、概览、有限证据检索和数据源信息；未实现快照生成、业务写入、抓取、模型调用、客户端配置写入或 B 阶段自动化。

## 改动与契约

- 新增 `bili_get_data_source_info`、`bili_list_events`、`bili_get_event_overview`、`bili_search_event_comments`；旧 3 个工具及所有 `mcp_contract_version=2` 字段未改名、未升版。
- 所有 7 个工具都使用严格输入 Schema、默认分页 20、最大 50、最大 offset 100000 与只读/非破坏/非开放世界/幂等注解。
- 新工具独立读取 `analysis_groups`、`analysis_group_items`、`analyses` 与 `comments`；未导入事件业务服务、运行入口、路由、网络或模型代码。
- 仅 `status=done` 且评论采集状态为 `completed` 的成员评论进入事件统计。缺失、未完成或部分采集成员明确写入 `limitations`，不伪装成零评论来源。
- LLM 模式只统计完整 V2 标签；返回覆盖数、分母和限制，绝不静默改用 NLP。无可信快照清单时 `snapshot_id` 与 `snapshot_created_at` 为 `null`，时间来源为 `unknown`，不使用文件 mtime。

## Fixture 与统计核对

隔离 fixture 覆盖：空库、双事件、多来源不均衡、同来源精确重复、缺失成员、部分采集成员、完整/部分/旧版 LLM 标签、特殊字符、超长文本、提示注入文本与 Cookie/API Key/路径哨兵。

- 事件 10 有 3 个成员和 8 条可纳入原始评论；`raw_share` 为 0.5/0.25/0.25，精确重复涉及 2 条评论。
- 事件 10 的 LLM 覆盖为 3/8，情绪分母为 3，且 `data_complete=false` 并说明未回退到 NLP。
- 事件 11 同时有部分采集与缺失成员；只有完整来源的 4 条评论进入统计，成员限制明确出现。
- 分页、来源筛选、零匹配、非法参数、缺表与事件列类型不兼容均有断言；每次读取前后 SHA-256 和目录项不变，无 WAL/SHM/journal 新增。

## 已运行命令与通过判定

| 工作目录 | 命令 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| 仓库根目录 | `.\\backend\\venv\\Scripts\\python.exe -m py_compile backend\\agent_mcp\\contracts.py backend\\agent_mcp\\read_only_service.py backend\\agent_mcp\\server.py backend\\tests\\test_agent_mcp.py scripts\\smoke-final-mcp.py` | 0 | 修改的 Python 文件可编译 |
| `backend` | `.\\venv\\Scripts\\python.exe -m unittest tests.test_agent_mcp tests.test_analysis_group_routes tests.test_analysis_group_migration -v` | 0 | 35 项 MCP、事件聚合和迁移回归通过 |
| 仓库根目录 | `git diff --check` | 0 | 无本阶段空白字符错误；仅保留无关诊断测试文件的 CRLF 提示 |

扩展后的 `scripts/smoke-final-mcp.py` 已强制发现和调用全部 7 个工具，但不能对仅内置旧 3 工具的 0.2.4 EXE 运行。R3 将构建本次版本化主 EXE 后，使用该脚本执行双会话 stdio 验收并记录新产物 SHA-256。

## 审查与阶段结论

独立审查曾发现事件来源数被评论 JOIN 放大、部分采集成员被误判可用；均已修复并新增回归断言。未发现 Critical 或 Required 残余。R1 仅可进入 R2 的用户主动快照与接入资料阶段，不授权或实现 B 阶段。
