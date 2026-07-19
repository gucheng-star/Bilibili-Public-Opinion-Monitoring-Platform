# B站视频评论区舆情监测平台 — Agent 开发规范

## 项目概述
Web 应用，分析 B站视频评论区的舆情数据。输入 BV 号或视频链接，抓取评论后进行情感分析、词云、地域分布、性别结构、热度趋势等多维度分析。

## 技术栈（不可变更）
| 层 | 技术 |
|----|------|
| 后端 | FastAPI (Python) + SQLite + SQLAlchemy |
| HTTP 客户端 | httpx |
| NLP | jieba + SnowNLP |
| 前端 | React + TypeScript + Vite |
| 包管理 | pnpm（禁止 npm / yarn） |
| 图表 | ECharts + echarts-for-react + echarts-wordcloud |
| 样式 | 纯 CSS（CSS 变量双主题，禁止 Tailwind） |
| Python | backend/venv（禁止系统 Python） |

## 代码编辑规范
- 所有文件编辑优先通过 apply_patch 工具完成
- 新建文件用 *** Add File:，增量用 *** Update File:
- ** *** Update File: @@ 一律不带行号**，行号格式（@@ -14,5 +14,6 @@）禁止使用
  - 工具内部 diff 行号基准与实际文件不对齐，模型生成行号也极易出错，必然匹配失败
  - 裸 @@ 做纯内容文本匹配，中文/ASCII 均可靠
  - 示例： *** Begin Patch; *** Update File: /path/to/file; 下一行 @@; 然后 +新增行; 再跟 上下文行（空格开头）; *** End Patch
- **优先定点编辑，避免全文重写**：哪怕改动跨多个不连续位置，也应拆成多个小 patch
- **apply_patch 连续两次匹配失败时，允许用 Python 脚本辅助**：先写 .py 到临时目录再运行，再复制到目标位置
- **禁止**：cat / Set-Content / heredoc 直接写入目标文件
- **禁止**：PowerShell @'...'@ | python - 管道传中文（UTF-8 必然损坏）
- **禁止**：Python inline -c 三层转义、Start-Process hidden 被沙箱杀

## 启动方式
```bash
cd backend && venv\Scripts\activate && python -m uvicorn main:app --host 0.0.0.0 --port 8000
# 前端开发
cd frontend && pnpm run dev
# 生产：先 pnpm run build 再启动后端
```
访问 http://localhost:8000/。Agent 无法保持后台进程，需用户手动启动。

## UI 设计规范
- 所有 UI 文字中文
- 主题：CSS 变量双主题，默认跟系统，可手动切换。切主题时 ECharts 必须重绘（MutationObserver + state + key）
- 布局：max-w-7xl 80rem 居中，第一行 2 列等宽（情感+性别），后续全宽。卡片等高用 md:grid-auto-rows-fr
- 响应式：移动端单列，桌面端多列，禁止固定宽度
- 动效：卡片 card-enter stagger、hover lift、header 呼吸线、modal scale+fade、进度条脉冲。必须适配 prefers-reduced-motion
- 图表：扇形无描边（禁 borderWidth/borderColor），颜色跟主题，切主题 key 重挂载
- 按钮：主 .btn-primary（#FB7299+流光），次 .btn-ghost，预览按钮透明 B站蓝 rgba(0,161,214,.12) 圆角 .625rem 不跟主题

## 功能约束
- 须扫码登录才能抓取评论，无硬编码 Cookie，登录仅用于抓取
- 可调抓取参数：总数、间隔
- 词云右侧词频列表可点击排除
- 历史记录登录后即显示，可删除（模态弹窗级联）

## 已知限制
- 年龄数据 B站 API 不提供
- 评论数受 API 分页限制
- 地域粒度仅到省份
- Agent 无法保持后台进程
