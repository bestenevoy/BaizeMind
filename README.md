# Agentic-GraphRAG

企业级多模态文档智能问答系统。融合 MinerU 文档解析、Neo4j 知识图谱、Milvus 向量检索、LangGraph Agent 与 Microsoft GraphRAG 的全链路知识管理平台。

**技术栈**: Python · FastAPI · LangGraph · PaddleOCR-VL · MinerU · BGE-M3 · Neo4j · Milvus · DeepSeek

## 环境要求

| 服务 | 端口 | 用途 |
|------|------|------|
| Milvus Standalone | 19530 | 向量检索 |
| Neo4j | 7687 (bolt) | 知识图谱 |
| DeepSeek API | remote | LLM 调用 |
| SiliconFlow API | remote | BGE-M3 Embedding |

## 快速启动

### 1. 配置环境变量

复制并编辑 `.env` 文件：

```bash
cp .env.example .env
```

必填配置：

```env
DEEPSEEK_API_KEY=sk-xxxx
SILICONFLOW_API_KEY=sk-xxxx
NEO4J_PASSWORD=your_password
```

### 2. 安装依赖

```bash
# Python 依赖
uv sync

# 前端依赖
cd frontend && npm install
```

### 3. 启动服务

```bash
# 终端 1：启动后端（端口 8000）
uv run -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 终端 2：启动前端（端口 3000，自动代理 /api → :8000）
cd frontend && npm run dev -- --host 0.0.0.0 
```

然后打开浏览器访问 `http://localhost:3000`。

## 命令行工具

```bash
# 导入文档
uv run python scripts/ingest_documents.py <file>

# 构建知识图谱
uv run python scripts/build_graph.py

# 构建 GraphRAG 索引
uv run python scripts/build_graphrag.py

# 运行评估
uv run python scripts/run_evaluation.py
```

## 故障排查

```bash
# 分层诊断（从环境到 Agent 逐层测试）
uv run python scripts/diagnose.py           # 全部
uv run python scripts/diagnose.py --quick   # 快速（跳过耗时测试）

# 单独测试某一层
uv run python scripts/diagnose.py --env      # 仅环境配置
uv run python scripts/diagnose.py --services # 仅服务连通性
uv run python scripts/diagnose.py --apis     # 仅 API 响应
uv run python scripts/diagnose.py --modules  # 仅 Python 模块
uv run python scripts/diagnose.py --milvus   # 仅 Milvus
uv run python scripts/diagnose.py --neo4j    # 仅 Neo4j
uv run python scripts/diagnose.py --parse --test-file <file>  # 仅文档解析
uv run python scripts/diagnose.py --retrieval # 仅检索流程
uv run python scripts/diagnose.py --agent    # 仅 Agent 流程
```

## 运行测试

```bash
# 安全测试（不需要外部服务）
uv run -m pytest tests/test_parser.py tests/test_chunker.py tests/test_graph.py -v

# 全部测试（需要 Milvus / Neo4j / 模型可用）
uv run -m pytest tests/ -v
```

## 项目结构

```
├── api/                    # FastAPI 路由：文档管理、问答、系统状态
├── config/                 # 配置（.env 加载）与 Prompt 模板
├── src/
│   ├── document_parser/    # MinerU / PaddleOCR-VL 文档解析
│   ├── chunker/            # 层次化分块、表格感知
│   ├── embeddings/         # BGE-M3 嵌入（本地 GPU 或 SiliconFlow API）
│   ├── retrieval/          # Milvus 向量 / BM25 / 混合 RRF / 重排序
│   ├── knowledge_graph/    # 实体抽取、Neo4j CRUD、GraphRAG 索引与查询
│   ├── agents/             # LangGraph 工作流：路由 → 检索 → 图谱 → 验证
│   ├── storage/            # SQLite 文档元数据（文件夹、标签）
│   └── evaluation/         # 评估数据集与指标
├── frontend/               # React 18 + Vite + Tailwind + shadcn/ui
├── scripts/                # CLI 工具
└── tests/                  # 测试
```

## 常见问题

**MinerU 解析报错**：MinerU CLI 位于 `.venv/bin/mineru`，不在系统 PATH。代码已自动解析，请勿直接调用 `mineru` 命令。

**前端类型检查**：`cd frontend && npx tsc --noEmit`

**前端生产构建**：`cd frontend && npm run build`
