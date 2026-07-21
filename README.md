# B站舆论监测平台

Bilibili Public Opinion Monitoring Platform — 输入 BV 号，自动抓取评论并进行多维度舆情分析。

## 功能

- **扫码登录** — B站 App 扫码，安全无侵入，Cookie 仅用于数据抓取
- **多维度分析** — 情感倾向、词云、地域分布、性别结构、热度趋势
- **双引擎分析** — NLP 三分类 + LLM 八分类（百炼 Qwen-Plus，Plutchik 情绪模型）
- **暗/亮双主题** — 跟随系统自动切换，支持手动切换并带过渡动画
- **丰富的图表** — ECharts 饼图/玫瑰图/中国地图/词云/折线图，全部支持一键下载
- **筛选过滤** — 按性别、日期、地域筛选评论
- **历史管理** — 自动保存分析结果，随时回顾或删除

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI (Python 3.12) + SQLite + SQLAlchemy |
| 前端 | React 19 + TypeScript + Vite |
| NLP | jieba 分词 + SnowNLP 情感分析 |
| LLM | 阿里百炼 Qwen-Plus (OpenAI 兼容) |
| 图表 | ECharts + echarts-for-react + echarts-wordcloud |
| 样式 | 纯 CSS（CSS 变量双主题） |

## 快速开始

### 环境要求

- Python 3.12+ + venv
- Node.js 24+ + pnpm
- (可选) 阿里百炼 API Key，用于 LLM 情感分析

### 安装运行

```bash
# 1. 后端
cd backend
python -m venv venv
venv\Scripts\activate      # macOS/Linux: source venv/bin/activate
pip install fastapi uvicorn httpx sqlalchemy jieba snownlp aiosqlite

# 2. 前端
cd frontend
pnpm install

# 3. 启动开发服务
# 终端 1 — 后端 (端口 8000)
cd backend && venv\Scripts\activate && python -m uvicorn main:app --port 8000 --reload

# 终端 2 — 前端 (端口 5173)
cd frontend && pnpm run dev
```

浏览器打开 **http://localhost:5173**。

### 生产构建

```bash
cd frontend && pnpm run build
# 构建产物在 frontend/dist/，后端自动服务
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## 项目结构

```
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── api/                 # 路由 (routes, auth_routes, settings_routes)
│   ├── services/            # 业务逻辑 (bilibili, sentiment, LLM, wordcloud, ...)
│   ├── models/              # SQLAlchemy 模型 (database.py)
│   └── venv/                # Python 虚拟环境 (gitignored)
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # 主应用
│   │   ├── components/      # 14 个组件
│   │   ├── services/api.ts  # API 客户端
│   │   └── types/           # TypeScript 类型定义
│   └── public/china.json    # ECharts 中国地图数据
└── PROJECT.md               # 详细开发文档
```

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/*` | 扫码登录、状态、退出、账号管理 |
| POST | `/api/analyze` | 提交 BV 号，异步分析 |
| POST | `/api/reanalyze/{id}` | 对已有结果用 LLM 重新分析 |
| GET | `/api/status/{id}` | 查询分析进度 |
| GET | `/api/results/{id}` | 获取完整分析结果 |
| GET | `/api/wordcloud/{id}` | 词云图片 (base64) |
| GET | `/api/history` | 历史记录列表 |
| DELETE | `/api/history/{id}` | 删除历史 (级联删除) |

## License

MIT
