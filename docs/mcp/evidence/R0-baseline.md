# R0 验收证据：契约与基线

日期：2026-09-09
分支：`codex/agent-mcp-readonly-snapshots`
范围：仅 R0；未实现业务写入、抓取、模型调用、事件创建或自动化工作流。

## 工作区与运行时

- 核对前后保留的无关修改：`backend/api/runtime_routes.py`、`backend/tests/test_dev_diagnostics_routes.py`。它们未被暂存或修改。
- 当前基线分支为 `master...origin/master`，实施分支为 `codex/agent-mcp-readonly-snapshots`。
- 运行时：Git 2.54.0.windows.1、Python 3.12.0、pnpm 11.1.1、Cargo/Rustc 1.97.1。

## 已核对的现有实现

- `backend/agent_mcp/server.py` 注册 3 个 stdio 只读工具，并在中间件拒绝未知字段及不合法参数；工具注解为只读、非破坏、非开放世界和幂等。
- `backend/agent_mcp/contracts.py` 保持输出契约 `mcp_contract_version=2`，区分本地 NLP 三分类和完整 LLM V2 标签。
- `backend/agent_mcp/read_only_service.py` 使用静态本地路径检查、只读 immutable SQLite、authorizer、表/列白名单、5 秒查询截止和评论/响应上限；不导入业务运行入口。
- 事件数据模型是 `analysis_groups` 与稳定成员表 `analysis_group_items`；产品聚合位于 `backend/services/analysis_groups.py`。本轮将为 MCP 建立独立只读查询，不复用会触发写入、鉴权、网络或模型的运行服务。
- 当前没有 Agent/MCP 快照生成后端接口或设置页入口；当前示例配置仍要求手动提供数据库副本。主 EXE 已有 `--mcp-stdio` 分支、会话目录回收和更新协调锁。
- 当前最终 EXE 冒烟脚本只要求旧 3 工具；R1 将扩充工具集合与事件 fixture。

## 固定的兼容性决策

1. 不更改旧工具名、旧参数或 v2 字段语义；时间/快照信息通过新增数据源信息工具提供。
2. R1 新增 `bili_get_data_source_info`、`bili_list_events`、`bili_get_event_overview`、`bili_search_event_comments`，均为严格 Schema 的只读工具。
3. 快照生成只由桌面认证后的本地后端 API 发起，使用 SQLite backup；MCP 永远不写入数据库或创建快照。
4. 缺表或不兼容 Schema 是明确失败，不能伪装成零统计；快照缺可信清单时创建时间为 `null`。

完整字段草案、fixture 与客户端清单见 [契约文档](../contract.md)。

## 已运行命令与通过判定

| 工作目录 | 命令 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| 仓库根目录 | `git status --short --branch` | 0 | 识别并保留两处无关修改 |
| `backend` | `.\\venv\\Scripts\\python.exe -m unittest tests.test_agent_mcp -v` | 0 | 14 个 MCP 只读/stdio/Schema/安全测试通过 |
| `backend` | `.\\venv\\Scripts\\python.exe -m unittest tests.test_analysis_group_routes tests.test_analysis_group_migration -v` | 0 | 16 个事件聚合、LLM 覆盖、成员约束和迁移保护测试通过 |
| 仓库根目录 | `& .\\backend\\venv\\Scripts\\python.exe .\\scripts\\smoke-final-mcp.py 'F:\\project\\Bilibili Public Opinion Monitoring Platform\\dist\\portable\\BiliOpinionMonitor-0.2.4-windows-x64.exe'` | 0 | 30 秒单次协议超时；`sessions=2`、`tools=3`、旧工具各 2 次、临时目录和 SQLite sidecar 均为 0 |

本次基线 EXE：`F:\\project\\Bilibili Public Opinion Monitoring Platform\\dist\\portable\\BiliOpinionMonitor-0.2.4-windows-x64.exe`，122,802,688 字节，SHA-256 `8B33DAC08CF9B9C79D2E683DDDCA81D7556ED92B292869492DB8004589001B6B`。

该 EXE 冒烟是 R0 的历史能力基线，不是 R1-R3 的最终 EXE 验收。R3 必须基于本次构建的版本化 EXE 重跑扩展后的 smoke，并记录路径、字节数与 SHA-256。

## 阶段结论

- R0：待本阶段文档的格式检查、独立审查和提交完成后判定。
- 进入 R1 前提：保留 v2 兼容性，新增独立只读事件查询与可复现 fixture，不触碰 B 阶段写能力。
