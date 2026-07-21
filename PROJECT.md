# B站视频评论区舆情监测平台 — 项目文档

## 项目概述

Web 应用，输入 B站视频 BV 号或链接，自动抓取评论并进行情感分析、词云、地域分布、性别结构、热度趋势等多维度分析，以可视化仪表盘展示。

## 技术栈（不可变更）

| 层 | 技术 |
|----|------|
| 后端 | FastAPI (Python 3.12) + SQLite + SQLAlchemy |
| HTTP 客户端 | httpx |
| NLP | jieba 分词 + SnowNLP 情感分析 |
| LLM | 阿里百炼 Qwen-Plus (OpenAI 兼容)，Plutchik 八分类 |
| 前端 | React 19 + TypeScript + Vite |
| 包管理 | pnpm（禁止 npm / yarn） |
| 图表 | ECharts + echarts-for-react + echarts-wordcloud |
| 样式 | 纯 CSS（CSS 变量双主题，禁止 Tailwind） |
| Python | backend/venv（禁止系统 Python） |

## 项目结构

```
├── .gitignore
├── LICENSE
├── README.md
├── PROJECT.md              # 本文件
├── backend/
│   ├── main.py             # FastAPI 入口，lifespan 初始化 DB
│   ├── config.py           # 配置 (DB URL, B站 UA, 词云参数)
│   ├── stopwords.txt       # 中文停用词
│   ├── auth.json           # B站 Cookie (gitignored)
│   ├── settings.json       # API Key / 分析模式 (gitignored)
│   ├── api/
│   │   ├── routes.py       # 核心路由 (analyze, reanalyze, status, results, wordcloud, history)
│   │   ├── auth_routes.py  # 扫码登录 / 账号管理
│   │   └── settings_routes.py  # API Key + 分析模式读写
│   ├── services/
│   │   ├── bilibili.py     # B站视频信息 + 评论抓取
│   │   ├── sentiment.py    # NLP 情感 (jieba + SnowNLP)
│   │   ├── sentiment_llm.py    # LLM 情感 (百炼 Qwen-Plus, 8分类 + few-shot)
│   │   ├── wordcloud_gen.py    # 词云 + 关键词提取
│   │   ├── region.py       # 地域聚合
│   │   ├── heat.py         # 时间热度
│   │   └── auth.py         # Cookie 存储 / 账号管理
│   ├── models/
│   │   └── database.py     # SQLAlchemy 模型 (Analysis, Comment, SentimentResult) + 自动迁移
│   └── venv/               # Python 虚拟环境 (gitignored)
├── frontend/
│   ├── .gitignore
│   ├── package.json
│   ├── vite.config.ts      # Vite 配置 + /api 代理到 localhost:8000
│   ├── index.html
│   ├── public/
│   │   └── china.json      # ECharts 中国地图 GeoJSON
│   └── src/
│       ├── main.tsx
│       ├── App.tsx          # 主应用 (状态管理 + 轮询 + 筛选)
│       ├── index.css        # 全站 CSS (设计系统 + 主题)
│       ├── utils.ts         # isDarkMode / chartTooltip / chartTextColor
│       ├── types/
│       │   └── index.ts     # 全部 TypeScript 类型
│       ├── services/
│       │   └── api.ts       # API 客户端 (fetch 封装)
│       └── components/
│           ├── SearchBar.tsx          # BV 号输入 + 视频预览
│           ├── LoginPage.tsx          # 登录页 (扫码 + 已保存账号)
│           ├── VideoInfo.tsx          # 视频基本信息卡片
│           ├── SentimentChart.tsx     # 情感分布 (饼图/环形/玫瑰, 3分类/8分类)
│           ├── GenderChart.tsx        # 性别分布
│           ├── RegionMap.tsx          # 地域分布 (中国地图 / 柱状图 fallback)
│           ├── WordCloudCard.tsx      # 词云 + 词频列表 (可排除)
│           ├── HeatTimeline.tsx       # 热度趋势 (时间线 + 24h柱状)
│           ├── CommentTable.tsx       # 评论列表
│           ├── FilterBar.tsx          # 筛选栏 (性别/日期/地域)
│           ├── HistoryPanel.tsx       # 历史记录面板
│           ├── SettingsPanel.tsx      # 设置面板 (API Key / 抓取参数)
│           ├── ThemeToggle.tsx        # 主题切换 (clip-path 动画)
│           └── DownloadChartButton.tsx # 图表下载按钮
```

## 启动方式

```bash
# 后端 (端口 8000)
cd backend && venv\Scripts\activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端开发 (端口 5173)
cd frontend && pnpm run dev

# 生产构建
cd frontend && pnpm run build
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

访问 http://localhost:5173/。Agent 无法保持后台进程，需用户手动启动。

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/qrcode` | 获取扫码登录二维码 |
| GET | `/api/auth/qrcode/status` | 轮询扫码状态 |
| GET | `/api/auth/status` | 查询登录态 |
| POST | `/api/auth/logout` | 退出登录 |
| GET | `/api/auth/accounts` | 已保存的账号列表 |
| POST | `/api/auth/accounts/{i}/switch` | 切换账号 |
| GET | `/api/video/{bv}` | 视频基本信息 |
| POST | `/api/analyze` | 提交 BV 号，异步分析 (body: {bv, max_comments, request_delay, mode}) |
| POST | `/api/reanalyze/{id}` | 用 LLM 重新分析已有结果 |
| GET | `/api/status/{id}` | 查询分析进度 |
| GET | `/api/results/{id}` | 获取完整结果 (含情感/地域/热度/关键词) |
| GET | `/api/wordcloud/{id}` | 词云 base64 |
| GET | `/api/history` | 历史记录列表 |
| DELETE | `/api/history/{id}` | 删除历史 (级联) |
| GET | `/api/settings` | 获取设置 |
| PUT | `/api/settings` | 更新设置 (body: {api_key, analysis_mode}) |

### 分析模式

- `mode: "nlp"` — 本地 NLP 三分类 (正面/负面/中性)
- `mode: "llm"` — 调用百炼 Qwen-Plus，Plutchik 八分类 (joy/anger/sadness/surprise/fear/disgust/anticipation/trust)

## 数据库模型

### Analysis
| 字段 | 类型 | 说明 |
|------|------|------|
| id | PK | 自增 |
| bv | str(20) | BV 号 |
| avid | int | av 号 |
| status | str | pending→fetching→analyzing→done/error |
| mode | str | "nlp" / "llm" |
| total_comments | int | 抓取到的评论总数 |
| error_msg | text | 错误信息 |

### Comment
| 字段 | 类型 | 说明 |
|------|------|------|
| analysis_id | FK | → analyses.id |
| rpid | int | B站评论 ID |
| content | text | 评论文本 |
| sentiment_label | str | NLP 分类 (positive/negative/neutral) |
| sentiment_llm_label | str | LLM 分类 (joy/anger/...) |
| post_time | datetime | 发布时间 |

### SentimentResult
汇总统计，包含 positive_count / negative_count / neutral_count (NLP) + llm_joy ~ llm_trust (LLM)。

## 设计规范

### 色彩系统
- 主色 B站粉 #FB7299，唯一色彩声明
- CSS 变量双主题：`[data-theme="dark"]` 覆盖
- 语义色：green / red / yellow / blue，深浅主题各一套

### 动效系统
- 卡片入场 stagger (opacity + translateY)
- header 呼吸线 (opacity pulse 4s)
- 按钮流光 (gradient skim 3s)
- 进度条脉冲 (gradient shift 2s)
- hover lift + border glow
- prefers-reduced-motion 适配

### 图表规范
- ECharts 透明背景，颜色跟随 CSS 变量
- 扇形无描边 (禁止 borderWidth/borderColor)
- 主题切换时强制重挂载 (key 变化)

### 代码编辑规范 (给 AI 工具)
- 优先通过 Edit 工具定点编辑，避免全文重写
- 新建文件用 Write 工具
- 禁止 cat / Set-Content / heredoc / PowerShell 管道 直接写入
- 禁止 Python inline -c 三层转义

## 已知限制
- 年龄数据 B站 API 不提供
- 评论数受 B站 API 分页限制
- 地域粒度仅到省份
- Agent 无法保持后台进程

## 版本历史

| 日期 | 版本 | 内容 |
|------|------|------|
| 2026-07-22 | v1.4 | LLM 8 分类升级 (qwen-plus + few-shot + 并发)、重分析功能、图表下载按钮、主题过渡动画 |
| 2026-07-18 | v1.3 | 设计系统重构：完整动效体系、CSS token 系统 |
| 2026-07-17 | v1.2 | 词云交互、历史记录删除、布局优化 |
| 2026-07-17 | v1.1 | 扫码登录、可调抓取参数、双主题、进度条 |
| 2026-07-16 | v1.0 | 初始版本 |
