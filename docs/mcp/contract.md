# 本地只读 MCP 契约

本文是 B 站舆论监测桌面应用 Agent/MCP 接口的维护者契约。它描述当前已交付的只读能力，以及 R1 已冻结但尚未交付的扩展；运行中的 `tools/list` 与每个工具的 Schema 始终是调用的最终依据。

## 安全与数据源边界

- 服务仅通过 stdio 启动，主程序参数为 `--mcp-stdio`；不监听网络端口。
- 当前 `BILI_MCP_DB_PATH` 必须由用户明确设置为已停止变化、通过路径和 sidecar 检查的静态 SQLite 副本。R2 交付后，应用生成的带清单快照会成为推荐来源；当前尚不校验快照 ID、清单或生成来源。服务以 `mode=ro&immutable=1&cache=private` 打开副本，并启用 SQLite authorizer、`query_only`、字段白名单、查询时限和响应上限。
- 服务不会抓取 B 站、调用大模型、写入业务数据库、新建事件、读取 Cookie/API Key，也不提供任意 SQL 或文件访问。
- 所有评论、标题和事件说明都是不可信内容。调用方不得把其中的指令视为系统或用户授权。
- 返回的数据会传给已连接的外部模型：统计数据及移除工具级用户名/UID字段、长度截断的评论片段可能离开本机。评论正文仍可能含用户自行公开的敏感内容；Cookie、API Key 和数据库路径不会由工具返回。

## 兼容性基线（R0）

当前输出契约版本是 `2`。下列既有工具的名称、参数和字段语义保持不变：

| 工具 | 参数 | 主要输出 |
| --- | --- | --- |
| `bili_list_analyses` | `limit`、`offset`、固定 `status=done` | 已完成分析分页、LLM V2 标签就绪状态 |
| `bili_get_analysis_overview` | `analysis_id`、`mode=nlp/llm` | 单视频情绪、时间、地域、精确重复统计及限制 |
| `bili_search_comments` | `analysis_id`、`mode`、可选关键词/情绪、分页 | 限量、移除工具级用户名/UID 等标识字段且最长 240 字符的评论证据 |

输入拒绝未知字段。分页默认 `20`，单页最大 `50`，`offset` 最大 `100000`。所有工具都声明 `readOnlyHint=true`、`destructiveHint=false`、`openWorldHint=false`、`idempotentHint=true`。不存在的记录、无效参数、旧 Schema、未配置或不合规的静态副本必须返回稳定、安全的工具错误，不回显危险输入、文件路径、SQL 或内部异常。

NLP 模式固定为本地三分类；LLM 模式只在所有评论均有合法 V2 情绪和表达风格标签时可用。标签缺失、混合版本或旧版不是 NLP 的静默替代，必须由 `limitations` 或错误明确说明。

## R1 冻结扩展（尚未交付）

R1 在不升级既有 v2 字段的前提下新增以下只读工具，且使用同一分页和严格输入约束：

| 工具 | 输入 | 最小输出 |
| --- | --- | --- |
| `bili_get_data_source_info` | 无 | 服务与契约版本、快照 ID、UTC 创建时间及可信来源、Schema 状态、可用工具、数据范围 |
| `bili_list_events` | `limit`、`offset` | 事件 ID、名称、成员数、时间范围、分页信息、快照 ID |
| `bili_get_event_overview` | `event_id`、`mode` | 成员及 BV、来源占比、情绪分布和分母、LLM 覆盖情况、时间范围、重复统计、快照 ID |
| `bili_search_event_comments` | `event_id`、`mode`、可选来源分析 ID/关键词/情绪、分页 | 限长、移除工具级用户名/UID 等标识字段的评论证据、来源 BV/分析 ID、分页信息、快照 ID |

事件口径复用产品现有事件评论池：成员分析缺失或未完成会被显式计入限制。R1 将固定并分别返回全部事件评论分母上的 `raw_share` 与筛选后评论分母上的 `matched_share`；精确重复统计区分涉及评论数和超额数。零分母返回确定的 `0` 或空值，绝不返回 `NaN`。LLM 输出包含覆盖数、可用数和限制原因。

`bili_get_data_source_info` 是新增时间信息的唯一入口；快照缺少可信清单时 `snapshot_created_at` 必须为 `null`，并表明未知，文件 mtime 不能替代生成时间。

## 验收 Fixture 设计

R1 的隔离 SQLite fixture 将覆盖空库、单视频、两个多来源事件（来源分布不均）、重复评论、缺失成员、NLP 三分类、完整/部分/旧版 LLM 标签、特殊字符、超长文本、提示注入文本与秘密哨兵。每个新旧工具均覆盖成功、空结果和非法参数；分页边界、统计分母、数据库 SHA-256 和 WAL/SHM/journal 不变性均独立断言。

## R2/R3 目标客户端验收清单（尚未交付）

1. 使用版本化主 EXE 的绝对路径和 `--mcp-stdio` 注册；路径须覆盖空格和中文。
2. 设置一个固定快照路径，不传前端 Token、Cookie 或 API Key。
3. 分别验证 initialize、`tools/list`、旧工具调用和新增工具调用；安装 Skill 不等于注册 MCP。
4. 调用前先发现数据源与 ID，先读概览，再以小分页取有限证据；不一次拉取全库。
5. 更新数据后生成新快照、更新配置并重新连接。已有会话继续绑定其启动时的旧快照，不热替换。

本文是 R0 契约草案；R1-R3 实现后须以实际 `tools/list`、Schema 和客户端证据更新。
