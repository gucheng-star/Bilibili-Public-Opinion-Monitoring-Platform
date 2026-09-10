# R2 验收证据：用户主动快照与桌面接入

日期：2026-09-10
分支：`codex/agent-mcp-readonly-snapshots`
范围：用户在桌面设置页主动生成一致 SQLite 快照、查看范围与本地接入配置；未实现业务写操作、后台自动快照、自动删除、自动改写客户端配置或 B 阶段能力。

## 已实现行为

- `POST /api/agent-snapshots` 仅允许既有桌面本地 Token 中间件后的桌面进程调用；仅在用户点击设置页按钮时生成快照。
- 后端使用 `sqlite3.Connection.backup()`，在 `data/agent-snapshots/<UUID>/` 临时目录写入 `database.sqlite3` 与 `manifest.json`，校验 SHA-256、Schema 和非敏感计数后以目录原子重命名发布。失败只清理本次临时目录，不覆盖或自动删除已发布快照。
- 清单包含 UUID、UTC 创建时间、应用/契约版本、数据库 SHA-256、SQLite Schema 信息以及分析/评论/事件计数；它不含 Cookie、API Key、UID、用户名或评论正文。
- MCP 只在桌面主程序传入的可信快照根目录内读取并校验清单；目录布局本身不足以建立信任。清单被篡改、格式错误或与数据库 SHA 不匹配时明确拒绝。手动或伪造静态副本仍返回 `snapshot_id=null`、`snapshot_created_at=null`、`snapshot_time_source=unknown`。
- 设置页显示快照时间、数据范围、哈希、本地数据库和清单路径。它只复制 JSON 配置或接入指引，绝不写入或覆盖任何 MCP 客户端配置；JSON 使用当前桌面主 EXE 绝对路径、`--mcp-stdio` 与快照数据库路径。
- 页面明确说明：连接外部模型后，统计和移除工具级身份标识字段、长度截断的评论片段可能发送给该模型；快照数据库本身仍是本地敏感文件。

## 已运行命令与通过判定

| 工作目录 | 命令 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| `backend` | `.\\venv\\Scripts\\python.exe -m unittest tests.test_agent_mcp tests.test_agent_snapshots tests.test_settings_routes -v` | 0 | 28 项 MCP、快照一致性/WAL、可信根锚与清单篡改、失败保留、桌面路由拒绝和设置回归通过 |
| `frontend` | `node --experimental-strip-types --test tests/agentSnapshotConfig.test.mjs` | 0 | 中文及空格路径在 JSON MCP 配置中保持原样 |
| `frontend` | `pnpm lint`、`pnpm build` | 0 | lint 通过；生产构建通过（现有大 chunk 警告仍存在） |
| `frontend/src-tauri` | `cargo fmt --check`、`cargo check`、`cargo test` | 0 | 格式/编译通过；27 项 Rust 测试通过，含当前 EXE 路径只读命令 |

## 未执行且不得替代的验收

- 当前浏览器预览处于未登录状态，设置页受现有登录门槛保护；本机 Python 环境也没有 Playwright，因此未完成真实 GUI 已登录会话的“生成快照→复制配置”验收。
- 未构建本次版本化最终 EXE，未以真实桌面主 EXE 完成接入或新旧会话快照隔离。R3 必须执行这些步骤并记录实际产物哈希；当前 Rust 单测和前端构建不能替代它们。

## 阶段结论

代码级快照、清单、MCP 识别和设置页接入已由定向测试覆盖；真实 GUI/最终 EXE 验收保留为 R3 的明确未执行项。R2 可进入 R3 的公开文档、Skill、可重建配套包与最终集成验证，不进入 B 阶段。
