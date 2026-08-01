# B站舆论监测平台

Bilibili Public Opinion Monitoring Platform — 输入 BV 号，自动抓取评论并进行多维度舆情分析。

## 功能

- **扫码登录** — B站 App 扫码，安全无侵入，Cookie 仅用于数据抓取
- **多维度分析** — 情感倾向、词云、地域分布、性别结构、热度趋势
- **双引擎分析** — NLP 三分类 + 可配置 LLM 八分类（Plutchik 情绪模型）
- **批量 LLM 分析** — 每批 5 条评论、最多 3 批并发，按评论 ID 校验分类结果并自动重试失败批次
- **AI 智能总结** — 对当前筛选统计和代表性评论生成一段舆情简报，并按筛选条件保存
- **多模型供应商** — 情绪分析和智能总结可分别使用百炼、DeepSeek 或自定义 OpenAI 兼容接口
- **暗/亮双主题** — 跟随系统自动切换，支持手动切换并带过渡动画
- **丰富的图表** — ECharts 饼图/玫瑰图/中国地图/词云/折线图，全部支持一键下载；图表隐藏 0 值分类，玫瑰图按数量降序排列
- **筛选过滤** — 性别、日期、地域和情绪共同驱动图表、评论列表与 AI 总结；NLP/LLM 模式分别提供三分类和八分类标签
- **历史管理** — 自动保存分析结果，随时回顾或删除

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI (Python 3.12) + SQLite + SQLAlchemy |
| 前端 | React 19 + TypeScript + Vite |
| NLP | jieba 分词 + SnowNLP 情感分析 |
| LLM | 百炼 / DeepSeek / 自定义 OpenAI 兼容接口 |
| 图表 | ECharts + echarts-for-react + echarts-wordcloud |
| 样式 | 纯 CSS（CSS 变量双主题） |

## 快速开始

### 环境要求

- Python 3.12+ + venv
- Node.js 24+ + pnpm
- (可选) 百炼、DeepSeek 或其他 OpenAI 兼容服务的 API Key

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

### 大模型分析说明

- 每个请求包含 5 条评论，最多并发 3 个批次。返回结果使用评论 ID 绑定并校验，单个失败批次最多重试 2 次。
- 情绪分析与智能总结拥有独立的供应商、模型、Base URL、API Key 和可选回退模型配置。
- 百炼默认使用 `qwen3.6-plus`，DeepSeek 默认使用 `deepseek-v4-flash`；模型 ID 均可编辑。
- 以当前实测为例，100 条评论约需 2 分 9 秒。实际耗时会受模型响应、网络和服务负载影响。

### AI 智能总结

- 总结只在用户点击“生成总结”或“重新生成”时调用模型，应用筛选不会自动产生费用。
- 后端对全部筛选结果计算精确统计，再选取最多 40 条、合计不超过 12,000 字的高赞与分层代表评论。
- 同一分析、同一筛选条件只保存最新总结；评论内容或情绪标签变化后，旧总结会标记为过期。
- API Key 保存在本机 `backend/settings.json`（已 gitignore），接口仅返回掩码，日志和总结记录不保存完整密钥。
- 自定义接口必须使用公网 HTTPS Base URL；本机和私网模型端点暂不支持。

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
│   ├── api/                 # 路由（分析、设置、智能总结、认证）
│   ├── services/            # 业务逻辑（抓取、情绪、通用 LLM、总结、图表）
│   ├── models/              # SQLAlchemy 模型 (database.py)
│   └── venv/                # Python 虚拟环境 (gitignored)
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # 主应用
│   │   ├── components/      # 页面与数据可视化组件
│   │   ├── services/api.ts  # API 客户端
│   │   └── types/           # TypeScript 类型定义
│   └── public/china.json    # ECharts 中国地图数据
└── PROJECT.md               # 详细开发文档
```

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/auth/*` | 扫码登录、状态、退出、账号管理 |
| POST | `/api/analyze` | 提交 BV 号，异步分析 |
| POST | `/api/reanalyze/{id}` | 对已有结果用 LLM 重新分析 |
| GET | `/api/status/{id}` | 查询分析进度 |
| GET | `/api/results/{id}` | 获取完整分析结果 |
| GET | `/api/wordcloud/{id}` | 词云图片 (base64) |
| GET | `/api/history` | 历史记录列表 |
| DELETE | `/api/history/{id}` | 删除历史 (级联删除) |
| GET/PUT | `/api/settings` | 读取或更新本机设置（密钥仅返回掩码） |
| POST | `/api/settings/models` | 从指定供应商获取可选模型列表 |
| POST | `/api/settings/test-llm` | 测试某项 AI 任务的模型连接 |
| GET | `/api/summaries/{id}` | 获取分析记录下已保存的智能总结 |
| POST | `/api/summaries/{id}` | 按当前筛选生成或覆盖智能总结 |

## License

MIT
