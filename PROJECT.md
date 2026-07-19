# B站视频评论区舆情监测平台 — 项目文档

## 项目概述

Web 应用，输入 B站视频 BV 号或链接，自动抓取评论并进行情感分析、词云、地域分布、性别结构、热度趋势等多维度分析，以可视化仪表盘展示。

## 核心技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI (Python) + SQLite + SQLAlchemy |
| HTTP | httpx (B站 API 调用) |
| NLP | jieba 分词 + SnowNLP 情感分析 |
| 前端 | React 19 + TypeScript + Vite |
| 图表 | ECharts + echarts-for-react + echarts-wordcloud |
| 样式 | 纯 CSS (CSS 变量驱动双主题) |
| 包管理 | pnpm |
| 版本 | Git |

## 项目结构

```
Bilibili Public Opinion Monitoring Platform/
├── backend/
│   ├── main.py
│   ├── config.py / stopwords.txt / auth.json
│   ├── api/         (routes.py, auth_routes.py)
│   ├── services/    (bilibili, sentiment, wordcloud_gen, region, heat, auth)
│   ├── models/      (database.py)
│   └── utils/       (bv_av.py)
├── frontend/
│   ├── src/
│   │   ├── App.tsx, main.tsx, index.css, utils.ts
│   │   ├── types/index.ts, services/api.ts
│   │   └── components/ (14 个组件)
│   └── public/china.json
└── PROJECT.md
```

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | /api/auth/* | 扫码登录、状态、退出、账号管理 |
| POST | /api/analyze | 提交 BV 号触发异步分析 |
| GET | /api/status/{id} | 查询分析进度 |
| GET | /api/results/{id} | 获取完整结果 |
| GET | /api/wordcloud/{id} | 词云图片 (base64) |
| GET | /api/history | 历史记录 |
| DELETE | /api/history/{id} | 删除历史 (级联) |
| GET | /api/video/{bv} | 视频基本信息 |

## 启动方式

```bash
# 后端 (端口 8000)
cd backend && venv\Scripts\activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端开发 (端口 5173)
cd frontend && pnpm run dev

# 生产构建后仅需后端 (自动服务前端 dist)
cd frontend && pnpm run build
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## 版本历史

| 日期 | 版本 | 内容 |
|------|------|------|
| 2026-07-18 | v1.3 | 设计系统重构：完整动效体系、CSS token 系统、header 呼吸线、卡片入场 stagger、弹窗 scale+fade、进度条脉冲、hover lift、reduced-motion 适配 |
| 2026-07-17 | v1.2 | 词云交互 (词频列表+点击排除)、历史记录删除、布局优化 |
| 2026-07-17 | v1.1 | 扫码登录、可调抓取参数、双主题、进度条 |
| 2026-07-16 | v1.0 | 初始版本 |
---
# 前端设计规范 v2

## 1. 设计哲学

**一个风险，一个签名**: B站粉 (#FB7299) 是唯一的色彩声明，header 下方 2px 呼吸线是唯一的装饰性动效。其余一切保持克制。深色是"夜色数据舞台"，浅色是"晨间分析工坊"。

## 2. 色彩系统

### 深色主题 `[data-theme="dark"]`

| Token | 值 | 用途 |
|-------|-----|------|
| --bg | #070B14 | 页面底色 |
| --bg-card | #0F1629 | 卡片底色 |
| --accent | #FB7299 | B站粉 |
| --accent-glow | rgba(251,114,153,.32) | 发光 |
| --text-primary | #E2E8F0 | 主文字 |
| --text-secondary | #94A3B8 | 辅助 |
| --text-muted | #64748B | 弱化 |
| --border | rgba(148,163,184,.08) | 分割线 |
| --shadow-hover | 0 4px 20px rgba(0,0,0,.30) | 悬停阴影 |

### 浅色主题

| Token | 值 |
|-------|-----|
| --bg | #F6F3F0 |
| --bg-card | #FFFFFF |
| --shadow-hover | 0 4px 16px rgba(0,0,0,.06) |

### 语义色

| Token | 深色 | 浅色 |
|-------|------|------|
| --green | #34D399 | #059669 |
| --red | #F87171 | #DC2626 |
| --yellow | #FBBF24 | #D97706 |
| --blue | #38BDF8 | #2563EB |

## 3. 动效系统

### 入场动效

| 动效 | CSS 类 | 描述 |
|------|--------|------|
| 卡片入场 | .card-enter | opacity + translateY, 50ms stagger |
| 弹窗 | .modal-content | scale .92->1 + fade |
| 遮罩 | .modal-backdrop | fade |
| Toast | .toast | slide-down + fade |

### 持续性动效

| 动效 | 元素 | 周期 |
|------|------|------|
| 呼吸线 | .header-accent-line | opacity .35-.75, 4s |
| 按钮流光 | .btn-primary::after | gradient skim, 3s |
| 进度条脉冲 | .progress-bar-fill | gradient shift, 2s |
| 加载点 | .pulse-dot | box-shadow 扩散, 1.8s |
| 浮动 | .animate-float | translateY 0--3px, 3s |

### 微交互

| 触发 | 效果 | 时长 |
|------|------|------|
| 卡片 hover | lift 2px + border glow + shadow | .25s |
| 按钮 active | scale(.975) | instant |
| 搜索框 focus | border accent + double glow ring | .25s |
| 主题切换 | CSS 变量过渡 | .35s |

### Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    transition-duration: .01ms !important;
  }
}
```

## 4. 组件规范

| 组件 | CSS 类 | 说明 |
|------|--------|------|
| 卡片 | .card | 唯一表面容器，禁止嵌套 |
| 主按钮 | .btn-primary | 粉色背景 + 流光 |
| 次按钮 | .btn-ghost | 透明 + 边框 |
| 图标按钮 | .btn-icon | 2.25rem 正方形 |
| 搜索框 | .search-input | 3rem 高, focus 发光环 |
| 进度条 | .progress-bar-track / .progress-bar-fill | 脉冲渐变 |
| 弹窗 | .modal-overlay / .modal-backdrop / .modal-content | 居中遮罩 |
| Toast | .toast | 顶部居中 |

## 5. 布局

3 行 + 评论列表: Row 1 三列等宽 / Row 2 词云全宽 / Row 3 热度全宽，max-w-7xl (80rem) 居中，移动端单列堆叠。

## 6. 图表规范

ECharts 透明背景，颜色跟随 CSS 变量。通过 isDarkMode() 检测主题动态设置 option。
