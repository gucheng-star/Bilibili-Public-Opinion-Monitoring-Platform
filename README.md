# B站舆论监测平台

Bilibili Public Opinion Monitoring Platform — 输入 BV 号，自动抓取评论并进行多维度舆情分析。

## 功能

- **扫码登录** — B站 App 扫码，安全无侵入，Cookie 仅用于数据抓取
- **多维度分析** — 情感倾向、词云、地域分布、性别结构、热度趋势
- **NLP 优先的双引擎分析** — 新分析固定先运行本地 NLP 三分类，用户主动切换后才调用可配置的 LLM 八分类（Plutchik 情绪模型）
- **批量 LLM 分析** — 每批 5 条评论、最多 3 批并发，按评论 ID 校验分类结果并自动重试失败批次
- **AI 智能总结** — 对当前筛选统计和代表性评论生成一段舆情简报，并按筛选条件保存
- **多模型供应商** — 情绪分析和智能总结可分别使用百炼、DeepSeek 或自定义 OpenAI 兼容接口；模型与回退模型从供应商列表中选择
- **暗/亮双主题** — 跟随系统自动切换；手动切换以主题按钮为中心，浅色向外展开、深色向内收拢
- **丰富的图表** — ECharts 饼图/玫瑰图/中国地图/词云/折线图，全部支持一键下载；成对图表保持等宽，地域地图按排名选择代表性省份标注
- **筛选过滤** — 性别、时间维度、地域和情绪共同驱动图表、评论列表与 AI 总结；时间支持快捷范围和自定义双月日历，NLP/LLM 模式分别提供三分类和八分类标签
- **历史管理** — 自动保存分析结果，随时回顾或删除
- **可感知的任务进度** — 抓取进度按已获取评论数实时更新，AI 总结等待时循环显示打字机状态；长评论以定长摘要展示，完整内容由悬浮详情承载
- **沉浸式登录页** — 全屏信号观测主题背景、左右分栏圆角工作台与登录区内昼夜切换

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

- 首次提交分析不会调用大模型，而是先完成本地 NLP。只有用户在结果页主动切换到“大模型八分类”时，才会调用 `/api/reanalyze/{id}`。
- 每个请求包含 5 条评论，最多并发 3 个批次。返回结果使用评论 ID 绑定并校验，单个失败批次最多重试 2 次。
- LLM 重分析失败时保留已经完成的 NLP 结果和可用界面，不会把整条分析记录标记为不可用。
- 情绪分析与智能总结拥有独立的供应商、模型、Base URL、API Key 和可选回退模型配置。
- 配置供应商、Base URL 和 API Key 后，先点击“获取模型列表”，再从下拉列表选择主模型与回退模型，避免手工输入错误。切换供应商或修改 Base URL 后需要重新获取。
- 百炼初始推荐 `qwen3.6-plus`，DeepSeek 初始推荐 `deepseek-v4-flash`；最终可用模型以供应商接口返回的列表为准。自定义接口需要兼容 OpenAI 的 `GET /models` 才能提供选择列表。
- 百炼与 DeepSeek 请求会关闭思考模式，避免推理内容占满输出预算后返回空正文。设置页的“测试连接”会走与实际情感分析相同的结构化分类链路。

### AI 智能总结

- 总结只在用户点击“生成总结”或“重新生成”时调用模型，应用筛选不会自动产生费用。
- 后端对全部筛选结果计算精确统计，再选取最多 40 条、合计不超过 12,000 字的高赞与分层代表评论。
- 同一分析、同一筛选条件只保存最新总结；评论内容或情绪标签变化后，旧总结会标记为过期。
- API Key 保存在本机设置文件中，Windows 桌面版使用当前用户的 DPAPI 加密；接口仅返回掩码，日志和总结记录不保存完整密钥。
- 自定义接口必须使用公网 HTTPS Base URL；本机和私网模型端点暂不支持。

### 生产构建

```bash
cd frontend && pnpm run build
# 构建产物在 frontend/dist/，后端自动服务
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### Windows 便携桌面版（Beta）

桌面版采用 Tauri v2 外壳，并把 PyInstaller `onefile` 本地后端嵌入同一个 EXE。抓取、
Cookie、模型密钥、SQLite 数据库和分析过程均留在用户电脑；应用数据位于 EXE 同级自动
创建的 `data/`，不会上传到 Vercel 或其他应用服务器。把 EXE 与 data 复制到另一台电脑时
历史记录仍可读取，但 Cookie 和模型密钥因 DPAPI 绑定当前 Windows 用户，需要重新登录和输入。

```powershell
# 构建供 Tauri 嵌入的无控制台 onefile 后端
cd backend
.\build_portable_backend.ps1 -OutputDirectory dist

# Tauri 单文件可执行程序（不生成安装器）
cd ..\frontend
pnpm run tauri:build

# 输出单个便携 EXE
cd ..
.\scripts\assemble-portable.ps1 -Version 2.0.0-beta.1
```

开发架构、目录和更新安全协议见 `docs/DESKTOP_ARCHITECTURE.md`。正式在线更新还需要在
GitHub Actions 中配置 Ed25519 私钥和对应公钥；未配置公钥的本地测试构建会禁用在线更新。

### 验证

```bash
cd backend
venv\Scripts\python.exe -m unittest discover -s tests -v

cd ../frontend
pnpm run lint
pnpm run build -- --configLoader runner
```

### 常见问题

- `attempt to write a readonly database`：这属于本机 SQLite 文件或目录写权限问题，不是 B站拒绝访问。请确认后端进程以正常用户权限运行，并且 `backend/` 与数据库文件可写。
- `模型返回了空内容`：请先更新到包含 DeepSeek 关闭思考参数的版本，并在设置页重新测试情感分析配置；首次分析仍会优先使用本地 NLP。

## 项目结构

```
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── api/                 # 路由（分析、设置、智能总结、认证）
│   ├── services/            # 业务逻辑（抓取、情绪、通用 LLM、总结、图表）
│   ├── models/              # SQLAlchemy 模型 (database.py)
│   └── venv/                # Python 虚拟环境 (gitignored)
└── frontend/
    ├── src/
    │   ├── App.tsx          # 主应用
    │   ├── components/      # 页面与数据可视化组件
    │   ├── services/api.ts  # API 客户端
    │   └── types/           # TypeScript 类型定义
    ├── public/china.json    # ECharts 中国地图数据
    └── src-tauri/           # Windows 单文件便携外壳与内置更新模式
```

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/auth/*` | 扫码登录、状态、退出、账号管理 |
| POST | `/api/analyze` | 提交 BV 号，异步抓取并执行本地 NLP |
| POST | `/api/reanalyze/{id}` | 对已有结果用 LLM 重新分析 |
| GET | `/api/status/{id}` | 查询分析进度 |
| GET | `/api/results/{id}` | 获取完整分析结果 |
| GET | `/api/wordcloud/{id}` | 词云图片 (base64) |
| GET | `/api/history` | 历史记录列表 |
| DELETE | `/api/history/{id}` | 删除历史 (级联删除) |
| GET/PUT | `/api/settings` | 读取或更新本机设置（密钥仅返回掩码） |
| POST | `/api/settings/models` | 从指定供应商获取可选模型列表 |
| POST | `/api/settings/test-llm` | 按指定任务的真实调用链测试模型连接 |
| GET | `/api/summaries/{id}` | 获取分析记录下已保存的智能总结 |
| POST | `/api/summaries/{id}` | 按当前筛选生成或覆盖智能总结 |
| GET/POST | `/api/runtime/*` | 桌面后端健康、任务状态与退出准备 |

## License

MIT
