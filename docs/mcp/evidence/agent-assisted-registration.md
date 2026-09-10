# Agent 协助注册说明：验证记录

日期：2026-09-10

## 范围

本次仅更新公开接入说明与 `bili-opinion` Skill，不修改桌面应用、MCP 服务、数据库或最终 EXE。桌面应用继续只负责用户主动生成一致快照和复制 JSON；客户端配置写入仅由用户明确授权的本机 Codex Agent 执行。

## 交付内容

- `docs/mcp/README.md` 提供“整行授权提示 + 设置页复制 JSON”的最快接入方式，也保留可直接执行的 `codex mcp add` 单行命令。
- `skills/bili-opinion/SKILL.md` 规定 Agent 只有在同时获得完整 JSON 与“新增或更新”明确授权时，才能备份并处理同名 `bili-opinion-readonly` 条目。
- `skills/bili-opinion/references/setup.md` 记录检查、同名更新、重连和验证顺序；禁止改变其他 MCP、上传 JSON/数据库/备份，或把网页 ChatGPT 误作本机 Codex。

## 验证

| 项目 | 结果 |
| --- | --- |
| Skill 结构校验 | `quick_validate.py skills/bili-opinion` 通过；使用临时校验依赖与 UTF-8 模式，不修改项目或用户 Python 环境。 |
| 设置页 JSON | `node --experimental-strip-types --test tests/agentSnapshotConfig.test.mjs` 通过；含中文及空格的 EXE/快照路径保持原样。 |
| 包内容 | `scripts/package-agent-skill.ps1 -Version 0.2.4` 产物含 7 个白名单来源文件和 `manifest.json`，共 8 个条目。 |
| 可重建包 | 连续两次组装 SHA-256 均为 `b1d4bb04225d7130589a8963e7436520cc894deb8092160cd3e276c6b0426253`。 |

未对真实用户 Codex 配置执行注册测试，避免修改用户配置；注册命令、参数形式和本机配置范围依据当前 Codex CLI 帮助及官方 MCP 文档核对。最终 EXE 未重建，因为本次没有产品代码变更。
