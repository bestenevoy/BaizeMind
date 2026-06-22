# Agentic-GraphRAG 架构文档

## 系统概述

Agentic-GraphRAG 是一个面向企业知识管理与复杂文档问答场景的智能问答系统，融合了多模态文档解析、知识图谱构建、Hybrid RAG 与 Agent 推理能力。

**技术栈**: Python · FastAPI · LangChain · LangGraph · Microsoft GraphRAG · PaddleOCR-VL · MinerU · BGE-M3 · Neo4j · Milvus · DeepSeek API

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Layer                            │
│  POST /api/v1/documents/upload  │  POST /api/v1/qa/ask         │
│  GET  /api/v1/system/stats      │  POST /api/v1/qa/stream      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │    Agent Workflow        │
              │  (LangGraph StateGraph)  │
              └────────────┬────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
Query Router         Retrieval Agent         Graph Agent
    │                      │                      │
    │              ┌───────┴───────┐              │
    │              │               │              │
    ▼              ▼               ▼              ▼
Intent       Dense Search    BM25 Search   Cypher Query
Classify     (Milvus)        (rank-bm25)   (Neo4j)
    │               │               │              │
    │               └───────┬───────┘              │
    │                       ▼                      │
    │                 Hybrid Fusion                │
    │                 (RRF + Rerank)               │
    │                       │                      │
    │                       └──────────┬───────────┘
    │                                  │
    ▼ (holistic queries)               │
┌──────────────────┐                   │
│ Microsoft        │                   │
│ GraphRAG Search  │                   │
│ ┌──────────────┐ │                   │
│ │Global Search │ │ ← community      │
│ │(community    │ │   summaries      │
│ │ summaries)   │ │                   │
│ ├──────────────┤ │                   │
│ │Local Search  │ │ ← entity         │
│ │(entity       │ │   neighborhoods  │
│ │ neighbors)   │ │                   │
│ ├──────────────┤ │                   │
│ │DRIFT Search  │ │ ← hybrid         │
│ │(exploratory) │ │   exploration    │
│ └──────────────┘ │                   │
└────────┬─────────┘                   │
         │                             │
         └──────────┬──────────────────┘
                    ▼
            Answer Generator
                    │
                    ▼
            Answer Validator
                    │
                    ▼
           Final Answer + Citations
```

## 数据流

### 文档导入流程

```
原始文档 (PDF/Word/Excel/PPT/Image/TXT)
  │
  ├──[1]─► MinerU 解析 → Markdown + JSON 结构化内容
  │
  ├──[2]─► Chunk 切分
  │         ├─ HierarchicalChunker: 基于标题层级的语义切分
  │         ├─ TableChunker: 表格上下文感知切分 (保留表头)
  │         └─ ContextMerger: 相邻文本/表格合并，去重去噪
  │
  ├──[3]─► BGE-M3 Embedding → 密集向量 (1024维) + 稀疏词向量
  │
  ├──[4]─► Milvus 向量索引 (IVF_FLAT) + BM25 关键词索引
  │
  └──[5]─► 实体关系抽取 (DeepSeek LLM + LangExtract)
            └──► Neo4j 知识图谱构建
```

### 问答推理流程

```
用户查询
  │
  ├──► Query Router: 意图分类 (simple_fact / multi_hop / comparison / definition)
  │
  ├── simple_fact / definition:
  │     └──► Retrieval Agent → Hybrid Search (dense + BM25) → Rerank → 生成答案
  │
  ├── multi_hop:
  │     └──► Graph Agent → 实体提取 → 图谱路径扩展
  │           └──► Retrieval Agent → 补充检索 → 生成答案
  │
  └── comparison:
        └──► Retrieval Agent ⇄ Graph Agent (最多2轮交互)
              └──► 多实体对比检索 → 生成答案
```

## 模块说明

### 1. 文档解析 (src/document_parser/)
| 模块 | 职责 | 技术 |
|------|------|------|
| `mineru_parser.py` | PDF/Office 文档解析 | MinerU CLI，ModelScope 源 |
| `ocr_parser.py` | 扫描件/图片 OCR | PaddleOCR-VL-1.5 (native/vLLM) |
| `table_parser.py` | 表格解析与跨页合并 | HTML/Markdown 解析，表头匹配 |
| `chart_parser.py` | 图表描述生成 | OCR + DeepSeek VLM |
| `langchain_compat.py` | PaddleOCR 兼容补丁 | monkey-patch langchain 旧模块 |

### 2. Chunk 切分 (src/chunker/)
- **HierarchicalChunker**: 基于 Markdown H1-H6 标题层级构建树，每个 heading 下的正文使用 LangChain `RecursiveCharacterTextSplitter` 按语义边界递归切分，分隔符优先级：`\n\n` (段落) → `\n` (换行) → `。` (句号) → `！` (感叹号) → `？` (问号) → `；` (分号) → `，` (逗号) → 字符级硬切分。chunk_size=512, chunk_overlap=64。解决了中文文本 `text.split()` 无法按词切分导致整段变成一个超大 chunk 的问题
- **TableChunker**: 表格分片时保留表头和标题，>30行的大表自动拆分为多个子chunk
- **ContextMerger**: 相邻同类 chunk 合并 (max_merge_chars=1500)，去重去噪，同时过滤空文本 chunk 防止 embedding API 报错

### 3. Embedding (src/embeddings/)
- **BGE-M3**: 本地 FlagEmbedding (GPU) + SiliconFlow API 双路 fallback
- 输出: dense (1024维) + sparse (lexical weights)
- 支持最长 8192 tokens

### 4. 检索 (src/retrieval/)
| 模块 | 算法 | 说明 |
|------|------|------|
| `vector_retriever` | COSINE + IVF_FLAT | Milvus 密集向量检索 |
| `bm25_retriever` | Okapi BM25 | 关键词检索，jieba 分词 |
| `hybrid_retriever` | RRF (k=60) | dense(0.5)+sparse(0.3)+bm25(0.2) |
| `reranker` | LLM Rerank + TF-IDF fallback | 二次精排 |
| `graph_expander` | BFS 1-3 hop | 图谱邻居检索 |

### 5. 知识图谱 (src/knowledge_graph/)
- **EntityExtractor**: DeepSeek LLM few-shot / LangExtract 抽取
- **Neo4jManager**: Neo4j 连接管理，CRUD，MERGE 去重
- **GraphQuery**: Text-to-Cypher + 实体检索 + 路径查询

### 5b. Microsoft GraphRAG (src/knowledge_graph/)
集成微软 [GraphRAG](https://github.com/microsoft/graphrag) 框架，提供基于 Leiden 社区检测的层次化知识图谱能力：

| 模块 | 职责 | 技术 |
|------|------|------|
| `graphrag_indexer.py` | GraphRAG 索引构建 | Leiden 社区检测 + 社区摘要生成 |
| `graphrag_query.py` | 三种搜索模式 | Global / Local / DRIFT Search |

**GraphRAG 索引流程:**
1. 将已切分的文档 chunks 写入 GraphRAG input 目录
2. 运行 `graphrag index` 构建知识图谱
3. Leiden 算法自动检测社区结构，生成层次化社区摘要
4. 输出 parquet 文件 (communities, community_reports, entities, relationships)

**GraphRAG 搜索模式:**
- **Global Search**: 利用社区摘要进行 map-reduce 式全局推理，适合 "这些文档的主要主题是什么？" 类宏观问题
- **Local Search**: 基于实体邻域探索，适合 "X 实体的详细信息和关系" 类具体问题
- **DRIFT Search**: 混合模式，结合实体探索与社区上下文，适合探索性问题

**与自定义 GraphRAG 的关系:**
- 自定义 GraphRAG (Neo4j + LLM 抽取) 适合实时增量更新和精确查询
- Microsoft GraphRAG 适合离线批量索引和全局摘要推理
- 两者在 Agent 工作流中互补使用

### 6. Agent 框架 (src/agents/)
- **QueryRouter**: LLM 意图分类 → query_type (simple_fact/multi_hop/comparison/definition/holistic)
- **RetrievalAgent**: 混合检索 + 重排序
- **GraphAgent**: 实体提取 + 图谱扩展 + 上下文生成
- **GraphRAG Search**: 微软 GraphRAG 全局/本地/DRIFT 搜索 (holistic 类型路由)
- **AnswerValidator**: 幻觉检测 + 引用校验 + 答案优化
- **Workflow**: LangGraph StateGraph，5路条件路由，多轮迭代

### 7. 评测体系 (src/evaluation/)
- **数据集**: 105 条多类型 QA 样本 (definition/simple_fact/comparison/multi_hop)
- **指标**:
  - Recall@K (5/10): 检索文档覆盖率
  - Answer Accuracy: 语义相似度 + LLM Judge
  - Citation Accuracy: 引用来源匹配率
  - Hallucination Score: 幻觉检测评分

## LangGraph 工作流

```
START
  │
  ▼
[Query Router] ──分类──→
  │
  ├── simple_fact / definition → [Retrieval Agent] → [Answer Generator] → [Answer Validator]
  │                                                                              │
  ├── multi_hop / comparison → [Graph Agent] → [Retrieval Agent] → ... ─────────┤
  │                                                                              │
  └── holistic → [Microsoft GraphRAG Search] ──→ [Answer Generator] ─────────────┘
                      │                                                        │
                      ├── Global Search (社区摘要)                       (无效则循环, 最多5轮)
                      ├── Local Search (实体邻域)                              │
                      └── DRIFT Search (混合探索)                             END
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/documents/upload` | 上传文档，触发全流程处理 |
| GET | `/api/v1/documents/status/{id}` | 查询处理状态 |
| POST | `/api/v1/qa/ask` | 问答接口 |
| POST | `/api/v1/qa/stream` | SSE 流式问答 |
| GET | `/api/v1/system/stats` | 系统统计信息 |
| GET | `/health` | 健康检查 |

## 部署架构

```
┌──────────────────────────────────────────────────┐
│                    服务器                         │
│  ┌─────────────┐  ┌─────────────┐               │
│  │ FastAPI App  │  │ MinerU API  │               │
│  │   :8000      │  │   :8001     │               │
│  └──────┬───────┘  └─────────────┘               │
│         │                                        │
│  ┌──────┴───────────────────────────┐            │
│  │        外部服务                   │           │
│  │  ┌──────┐ ┌──────┐ ┌──────────┐ │           │
│  │  │Milvus│ │Neo4j │ │DeepSeek  │ │           │
│  │  │:19530│ │:7687 │ │  API     │ │           │
│  │  └──────┘ └──────┘ └──────────┘ │           │
│  └────────────────────────────────┘            │
│  ┌─────────────────────────────────┐           │
│  │        GPU (4×3090)             │           │
│  │  ┌─────────────┐ ┌───────────┐ │           │
│  │  │PaddleOCR-VL │ │BGE-M3     │ │           │
│  │  │(GPU 0-2)    │ │(GPU 3)    │ │           │
│  │  └─────────────┘ └───────────┘ │           │
│  └─────────────────────────────────┘          │
└──────────────────────────────────────────────────┘
```

## 目录结构

```
agentic-rag/
├── config/                    # 配置
│   ├── settings.py           # 全局配置 (pydantic-settings)
│   └── prompts.py            # Prompt 模板
├── src/
│   ├── document_parser/      # 文档解析
│   ├── chunker/              # Chunk 切分
│   ├── embeddings/           # BGE-M3 嵌入
│   ├── retrieval/            # 检索系统
│   ├── knowledge_graph/      # 知识图谱
│   ├── llm/                  # DeepSeek LLM
│   ├── agents/               # Agent 框架
│   └── evaluation/           # 评测体系
├── api/                       # FastAPI 服务
├── scripts/                   # 工具脚本
├── tests/                     # 测试
└── data/                      # 数据
```

## 快速启动

```bash
# 9. 测试 GraphRAG 全局搜索 (holistic 类问题)
curl -X POST http://127.0.0.1:8000/api/v1/qa/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "这些文档的主要主题是什么？", "stream": false}'
```

## 当前开发状态

### 已完成

| 模块 | 功能 | 状态 |
|------|------|------|
| 文档解析 | MinerU PDF/Office 解析、PaddleOCR-VL 图片 OCR、表格解析与跨页合并、图表描述 | 完成 |
| Chunk 切分 | 层次化标题切分 (HierarchicalChunker) + LangChain RecursiveCharacterTextSplitter (中英文语义边界感知)、表格感知切分 (TableChunker)、上下文合并+空文本过滤 (ContextMerger) | 完成 |
| Embedding | BGE-M3 密集+稀疏向量 (SiliconFlow API / 本地 GPU 双路 fallback) | 完成 |
| 向量检索 | Milvus IVF_FLAT 索引、增删查、expr 过滤 | 完成 |
| 关键词检索 | BM25 (jieba 分词)、增量追加、持久化 load/save | 完成 |
| 混合检索 | RRF 融合 (dense 0.5 + sparse 0.3 + BM25 0.2) + LLM Rerank + TF-IDF fallback | 完成 |
| 知识图谱 | LLM + LangExtract 实体关系抽取、Neo4j UNWIND 批量导入 (~50x 加速)、Cypher 查询、Text-to-Cypher | 完成 |
| GraphRAG | Microsoft GraphRAG 索引构建、Global/Local/DRIFT 三种搜索模式 | 完成 |
| Agent 工作流 | LangGraph StateGraph: 6 种查询类型分类、5 路条件路由、多轮迭代 (最多 5 轮) | 完成 |
| 答案验证 | 幻觉检测、引用校验、完整性评分 | 完成 |
| 文档存储 | SQLite 文档元数据 (文件夹/标签/状态)、LLM 自动标签 | 完成 |
| REST API | 文档 CRUD、Q&A (/ask + /stream SSE)、系统统计、健康检查 | 完成 |
| 前端 | React 18 + Vite + Tailwind + shadcn/ui: 3 页面 (首页/配置/测试)、3 栏布局、流式对话 | 完成 |
| 评测 | 105 条 QA 样本、Recall@K、语义相似度、LLM Judge、引用准确度 | 完成 |
| 诊断工具 | 8 层诊断脚本 (环境→服务→API→模块→解析→Milvus→Neo4j→Agent) | 完成 |
| 性能优化 | Neo4j UNWIND 批量插入 (~50x)、BM25 增量追加 (~5-10x)、embedding API 错误响应体捕获、中文 chunk 语义切分修复 | 完成 |

### 待完成 / 已知缺陷

| 位置 | 问题 | 优先级 |
|------|------|--------|
| `api/routes/management.py:261` | `POST /rebuild-indices` 端点返回 stub ("not fully implemented") | 高 |
| `src/agents/tools.py:44` | `rerank_results` 工具为 stub，未被 ALL_TOOLS 包含 | 高 |
| 知识图谱 | 删除文档时 Neo4j 中的实体/关系未同步删除 | 高 |
| `src/embeddings/bge_m3.py:48` | API 模式下 `encode_sparse()` 返回空列表，稀疏编码仅本地 GPU 可用 | 中 |
| 实体抽取 | 每个 chunk 串行调用 LLM，未并行化 (~10-20x 优化空间) | 中 |
| Embedding 批处理 | 串行 HTTP 调用，未并发派发 (~3-5x 优化空间) | 中 |
| 前端 | `config/`、`contexts/`、`hooks/`、`components/figma/` 目录为空 | 低 |
| 测试 | 无集成测试；`test_retrieval.py`、`test_agents.py::test_workflow_init` 在无外部服务时会 hang | 中 |
| 错误处理 | 多处 `pass` 静默吞噬异常 (见 `query_router.py`, `answer_validator.py`, `graph_agent.py`); `bge_m3.py` API 错误响应体现已包含详情 | 已修复/部分修复 |

### 最近提交 (4 commits)

| 提交 | 日期 | 描述 |
|------|------|------|
| `b7953e5` | 2026-06-13 | feat: show upload panel as dialog instead of inline |
| `9c188e1` | 2026-06-13 | perf: Neo4j UNWIND bulk insert + BM25 incremental append |
| `fd39f44` | 2026-06-12 | feat: add system configuration and connectivity check endpoints |
| `f5fe855` | 2026-06-12 | feat: initial commit — Agentic-GraphRAG system |
