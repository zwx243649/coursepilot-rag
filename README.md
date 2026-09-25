# CoursePilot

一个面向大学生实习作品集的课程资料 RAG 问答项目。它支持上传课程资料、建立向量索引、带引用回答，并使用 LangGraph 展示可解释的检索工作流。

模块划分、技术选型原因、实测效果和评测体系说明见 [`docs/项目说明.md`](docs/项目说明.md)。
面试讲解稿（30 秒版 / 2 分钟版 / 高频追问）见 [`docs/面试讲解.md`](docs/面试讲解.md)。
简历可直接使用的项目条目见 [`docs/简历条目.md`](docs/简历条目.md)。

## 技术栈

- 前端：原生 HTML、CSS、JavaScript，由 FastAPI 直接托管
- 后端：FastAPI、Pydantic、SQLAlchemy
- 关系数据库：PostgreSQL
- 向量数据库：Qdrant
- Agent 工作流：LangGraph
- 部署：Docker Compose
- 离线后备：SQLite、本地向量文件和抽取式回答

## 功能

- 课程与文档管理
- PDF、Markdown、TXT 上传、解析和切片
- 官方文档网址导入，可批量抓取同一文档路径下的页面
- 本地哈希 embedding 或 OpenAI 兼容 embedding API
- Qdrant 语义检索与课程过滤
- RAG 回答和原文引用
- LangGraph 状态流：问题分析、检索、相关性判断、生成或拒绝
- PostgreSQL 持久化课程、文档、会话与消息
- Hit Rate、MRR、关键词覆盖率和检索延迟评测
- 未配置模型 Key 时使用离线演示模式，拉取项目后即可运行

## 一键启动

需要 Docker Desktop 或 Docker Engine 与 Compose 插件。

```powershell
Copy-Item .env.example .env
docker compose up --build
```

打开 `http://localhost:8000`。API 文档位于 `http://localhost:8000/docs`。

首次启动会自动创建一个“AI 应用开发”示例课程，并完成文档索引。

## 本地开发

本地默认使用 SQLite、本地 JSON 向量存储和离线回答，不需要先启动 PostgreSQL 或 Qdrant。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn app.main:app --reload --app-dir backend
```

打开 `http://localhost:8000`。

也可以直接用仓库里的脚本启动和停止，脚本会自动等健康检查通过再返回。
如果系统禁用了 PowerShell 脚本执行（默认的 Restricted 策略），用 `.cmd` 版本：

```powershell
.\start.cmd
.\stop.cmd
```

## 接入 Embedding 模型

Embedding 接口使用独立的 `EMBEDDING_*` 配置，不与聊天模型共用 Base URL 和 Key。所有远程方案都要求服务提供 OpenAI-compatible `POST /embeddings`。

### OpenAI

```dotenv
EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=your-key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
EMBEDDING_BATCH_SIZE=64
EMBEDDING_SEND_DIMENSIONS=false
QDRANT_COLLECTION=coursepilot_openai_small
```

### Qwen Embedding

使用阿里云 DashScope 的 OpenAI-compatible 接口：

```dotenv
EMBEDDING_PROVIDER=qwen
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=your-dashscope-key
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=10
EMBEDDING_SEND_DIMENSIONS=false
QDRANT_COLLECTION=coursepilot_qwen_v3
```

### BGE Embedding

可以用 SiliconFlow、Xinference、vLLM 或 Ollama 暴露 OpenAI-compatible 接口。SiliconFlow 示例：

```dotenv
EMBEDDING_PROVIDER=bge
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=your-siliconflow-key
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=16
EMBEDDING_SEND_DIMENSIONS=false
QDRANT_COLLECTION=coursepilot_bge_m3
```

本机 Ollama 示例：

```dotenv
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
EMBEDDING_API_KEY=ollama
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024
QDRANT_COLLECTION=coursepilot_bge_m3_local
```

### 切换后的步骤

1. 修改 `.env`，并按模型真实输出维度修改 `EMBEDDING_DIM`。
2. 换一个新的 `QDRANT_COLLECTION` 名称，避免旧 collection 的维度冲突。
3. 重启 FastAPI 或重新执行 `docker compose up -d --build`。
4. 启动本地开发服务时使用 `uvicorn` 的命令；应用会自动读取项目根目录的 `.env`。
5. 调用重建索引接口，让已有文档使用新模型重新切片和向量化：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/system/reindex
```

也可以通过 `GET /api/system/health` 检查当前实际生效的 embedding provider、模型和维度。

### 聊天模型

生成回答的模型可以继续独立配置：

```dotenv
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-key
LLM_MODEL=gpt-4.1-mini
```

也可以把 `LLM_BASE_URL` 指向其他支持 OpenAI Chat Completions 接口的兼容服务。

## 导入主流框架官方文档

在课程页面点击“添加资料”，切换到“官方文档”，可以粘贴文档首页或直接使用预设入口：

- FastAPI：`https://fastapi.tiangolo.com/`
- Qdrant：`https://qdrant.tech/documentation/`
- LangGraph：`https://langchain-ai.github.io/langgraph/`
- PostgreSQL：`https://www.postgresql.org/docs/current/`

导入任务会在后台抓取、提取正文、切片并写入 Qdrant。`最多页面数` 控制单次导入规模，`限定在文档路径内` 可避免爬虫离开目标文档目录。也可以直接粘贴 GitHub 上 Markdown 文件的 `blob` 地址，系统会转换为 raw 地址。

## 项目结构

```text
.
├── backend
│   ├── app
│   │   ├── routers          # 课程、文档、问答、评测、系统接口
│   │   ├── services
│   │   │   ├── agent.py     # LangGraph 工作流
│   │   │   ├── embeddings.py
│   │   │   ├── ingestion.py
│   │   │   └── vector_store.py
│   │   ├── bootstrap.py     # 示例数据
│   │   ├── main.py
│   │   └── models.py
│   ├── tests
│   └── Dockerfile
├── frontend
├── docker-compose.yml
└── .env.example
```

## 请求链路

```text
Browser
  -> FastAPI
  -> LangGraph: analyze -> retrieve -> grade -> generate/refuse
  -> Qdrant: top-k vector retrieval
  -> PostgreSQL: metadata, conversation and message persistence
  -> LLM provider or offline extractive answer
```

## 运行测试

```powershell
python -m pytest backend\tests -q
```

测试使用 SQLite 与本地向量存储，不会修改 Docker 数据卷。

## 简历描述示例

> 基于 FastAPI、Qdrant 与 PostgreSQL 构建课程资料 RAG 问答系统，支持多格式文档入库、课程级向量过滤、引用溯源和 Docker Compose 一键部署。  
> 使用 LangGraph 实现“分析—检索—相关性判断—生成/拒绝”状态工作流，并建立离线评测集记录 Hit Rate、MRR 与检索延迟。
