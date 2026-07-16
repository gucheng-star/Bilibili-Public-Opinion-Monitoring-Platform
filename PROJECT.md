# B站舆论监测平台 - 项目需求文档

## 项目概述

一个Web应用，用于分析B站(Bilibili)视频评论区的舆情数据。输入视频BV号，自动抓取评论并进行多维度分析，以可视化仪表盘展示结果。

## 核心功能

### 1. 评论抓取
- 通过B站API抓取视频评论
- 支持Cookie认证（扫码登录）
- 防封策略：请求间隔3秒，单次最多100条
- 使用旧版评论API（x/v2/reply，sort=2按时间排序）
- 提取字段：内容、发布时间、点赞数、用户性别、IP属地

### 2. 用户认证（扫码登录）
- 调用B站 passport API 生成二维码
- 轮询扫码状态直至确认
- 成功后保存 SESSDATA Cookie 到本地 uth.json
- 支持多账号：最多保留5个历史账号，可快速切换
- 退出登录仅清除当前会话，保留文件
- **登录仅用于抓取评论数据，不获取其他个人信息**

### 3. 数据分析维度
| 模块 | 实现 | 输出 |
|------|------|------|
| 情感分析 | SnowNLP（正面/负面/中性） | 环形图 |
| 词云 | echarts-wordcloud（前端生成） | 词云图 |
| 地域分析 | IP属地 → 省份聚合 | 中国地图热力图 |
| 性别结构 | API返回的sex字段统计 | 饼图 |
| 热度趋势 | 评论发布时间序列 → 按时段聚合 | 折线图+24h柱状图 |
| ~~年龄结构~~ | B站API不提供，标注不支持 | - |

### 4. 前端界面
- React + TypeScript + Vite
- ECharts 图表（echarts-for-react）
- 明/暗双主题（默认跟随系统，可手动切换）
- **界面语言：中文**
- 3列仪表盘布局
- 登录页 → 欢迎说明 → 扫码/历史账号登录

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端框架 | FastAPI (Python) | 异步API |
| 数据库 | SQLite + SQLAlchemy | 轻量持久化 |
| HTTP客户端 | httpx | 调用B站API |
| NLP | jieba + snownlp | 分词+情感分析 |
| 前端框架 | React + TypeScript | Vite构建 |
| 包管理 | pnpm | - |
| 图表 | ECharts + echarts-for-react + echarts-wordcloud | - |
| 样式 | 纯CSS（CSS变量驱动主题） | - |
| 版本管理 | Git | - |

## 项目结构

`
b站舆论监测平台/
├── backend/
│   ├── main.py              # FastAPI入口
│   ├── config.py             # 配置（含停用词加载）
│   ├── stopwords.txt         # 停用词表（backend内部）
│   ├── auth.json             # 登录凭据（gitignore，自动生成）
│   ├── api/
│   │   ├── routes.py         # 分析API路由
│   │   └── auth_routes.py    # 认证API路由（QR登录）
│   ├── services/
│   │   ├── bilibili.py       # B站API客户端
│   │   ├── sentiment.py      # 情感分析
│   │   ├── wordcloud_gen.py  # 词云（已废弃，改用前端echarts-wordcloud）
│   │   ├── region.py         # 地域分析（IP属地→省份）
│   │   ├── heat.py           # 热度分析（时间序列）
│   │   └── auth.py           # 认证服务（QR登录、账号管理）
│   ├── models/database.py    # SQLAlchemy模型
│   └── utils/bv_av.py        # BV号↔AV号互转
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # 主应用（含登录守卫）
│   │   ├── main.tsx          # 入口
│   │   ├── index.css         # 全局样式（CSS变量主题）
│   │   ├── utils.ts          # 主题检测工具
│   │   ├── types/index.ts    # TypeScript类型
│   │   ├── services/api.ts   # API客户端
│   │   └── components/
│   │       ├── LoginPage.tsx      # 登录页（欢迎+扫码+历史账号）
│   │       ├── ThemeToggle.tsx    # 明暗主题切换
│   │       ├── SearchBar.tsx      # BV号搜索栏
│   │       ├── VideoInfo.tsx      # 视频信息卡
│   │       ├── SentimentChart.tsx # 情感分布环形图
│   │       ├── GenderChart.tsx    # 性别分布饼图
│   │       ├── RegionMap.tsx      # 地域分布地图/柱状图
│   │       ├── WordCloudCard.tsx  # 词云图（echarts-wordcloud）
│   │       ├── HeatTimeline.tsx   # 热度趋势图
│   │       ├── CommentTable.tsx   # 评论列表（可筛选/排序/分页）
│   │       └── HistoryPanel.tsx   # 历史记录横条
│   ├── public/china.json     # 中国地图GeoJSON（本地，不依赖CDN）
│   └── package.json
├── .gitignore
└── PROJECT.md                # 本文件
`

## 设计原则

### 界面
- **中文优先**：所有UI文字使用中文
- **双主题**：CSS变量驱动，默认跟随系统偏好，可手动切换
- **深色主题**：底色 #0A0E17，卡片 #131822，B站粉强调色 #FB7299
- **浅色主题**：暖白底色 #F6F3F0，白卡片，柔和阴影
- **ECharts图表**：tooltip/文字/地图底色均跟随主题自动切换

### 安全
- **无硬编码Cookie**：代码中不包含任何凭据
- **本地存储**：登录凭据仅保存在本机 uth.json，已加入 .gitignore
- **多账号隔离**：每个账号独立保存，切换方便

### API
- **认证接口**（不需登录）：/api/auth/*
- **分析接口**（需登录）：/api/analyze、/api/status/*、/api/results/*、/api/wordcloud/*、/api/history
- **IP属地提取**：B站 
eply_control.location 字段，格式 "IP属地：XX"，后端自动剥离前缀

## 已知限制
- 年龄数据：B站API不提供
- 评论数量：单次最多100条（可在config.py调整）
- 反爬：请求间隔3秒，依赖Cookie认证
- 地域粒度：仅到省份/国家级别