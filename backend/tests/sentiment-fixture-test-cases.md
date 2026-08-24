# 情感测试夹具用例

## 用途

本夹具用于在不抓取 B站真实评论、不调用付费模型的情况下，评估本地分析记录、评论树上下文和单一十分类情感标签。

- 开关：`BILI_ENABLE_TEST_FIXTURES=1`
- 创建夹具：`POST /api/test-fixtures/sentiment`
- 读取期望标签：`GET /api/test-fixtures/sentiment`
- 推荐流程：创建夹具 -> 打开历史记录 -> 主动执行 LLM 重分析 -> 对照下表检查输出

## 标签集合

单一十分类标签：

`neutral`、`joy`、`support`、`anticipation`、`surprise`、`anger`、`sadness`、`concern`、`disgust`、`sarcasm`

`sarcasm` 用于以反话、阴阳怪气或表面赞同表达否定，作为第十个主标签；不再单独输出表达方式。数据库既有 `sentiment_llm_style` 字段仅为历史记录兼容保留。

玩梗不是单独标签，应按评论主要情感归类；没有明确情绪时归为 `neutral`。

## 固定评论用例

| ID | 场景 | 期望情感标签 | 评论关系 |
| --- | --- | --- | --- |
| TC-01 | 事实计算 | neutral | 根评论 |
| TC-02 | 事实提问 | neutral | 回复 |
| TC-03 | 事实补充 | neutral | 二级回复 |
| TC-04 | 明确感谢 | support | 回复 |
| TC-05 | 轻度自嘲 | joy | 根评论 |
| TC-06 | 轻松玩笑 | joy | 回复 |
| TC-07 | 梗式复读 | neutral | 二级回复 |
| TC-08 | 请求后续选题 | anticipation | 回复 |
| TC-09 | 明确意外 | surprise | 根评论 |
| TC-10 | 认知反转 | surprise | 回复 |
| TC-11 | 风险担忧 | concern | 回复 |
| TC-12 | 直接批评 | anger | 根评论 |
| TC-13 | 反讽批评 | sarcasm | 回复 |
| TC-14 | 反驳反讽 | anger | 二级回复 |
| TC-15 | 反感标题党 | disgust | 回复 |
| TC-16 | 个人失落回忆 | sadness | 根评论 |
| TC-17 | 共情支持 | support | 回复 |
| TC-18 | 反讽式否定 | sarcasm | 根评论 |
| TC-19 | 现实担忧 | concern | 回复 |
| TC-20 | 荒诞接梗 | joy | 二级回复 |
| TC-21 | 明确认可 | support | 根评论 |
| TC-22 | 中性知识提问 | neutral | 回复 |
| TC-23 | B站短梗“6” | surprise | 根评论 |
| TC-24 | 理解与认可 | support | 回复 |

## API 与状态用例

### TC-F-001：创建夹具

前置条件：服务使用 `BILI_ENABLE_TEST_FIXTURES=1` 启动。

操作：调用 `POST /api/test-fixtures/sentiment`。

期望：返回一条已完成的 NLP 分析记录，包含固定 24 条评论；过程中不发出 B站抓取请求。

### TC-F-002：读取期望标签

前置条件：夹具 API 已启用。

操作：调用 `GET /api/test-fixtures/sentiment`。

期望：返回 24 个固定 ID 及其期望情感标签和评论关系；不返回独立表达方式期望。

### TC-ERR-001：关闭夹具 API

前置条件：未设置环境开关。

操作：调用任一夹具端点。

期望：API 返回 404，数据库中不写入测试分析。

## 上下文边界

- 根评论只发送当前评论。
- 一级回复发送根评论和当前评论。
- 二级回复最多发送根评论、直接父评论和当前评论。
- 不发送后代回复或无关兄弟评论。
- 上下文只辅助理解指代、玩梗和反讽，不能把上下文情感复制到当前评论。

## 覆盖矩阵

| 要求 | 覆盖 |
| --- | --- |
| 无抓取直接插入固定评论 | TC-F-001 与自动路由测试 |
| 20 至 30 条现实评论 | TC-01 至 TC-24 |
| 根评论、回复和二级回复 | TC-02/03、TC-06/07、TC-13/14、TC-18/20 |
| 中性回退 | TC-01/02/03/07/22 |
| 玩梗与反讽 | TC-06/07/13/18/20/23 |
| 支持与担忧新边界 | TC-04/11/17/19/21/24 |
| 关闭端点安全性 | TC-ERR-001 与自动路由测试 |

## 自动测试

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest tests.test_sentiment_test_fixtures tests.test_sentiment_context -v
```
