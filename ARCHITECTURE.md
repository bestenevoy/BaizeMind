# Agentic-GraphRAG 架构文档

## 定位

Agentic-GraphRAG 的准确架构分类是：

> **Hybrid RAG + Graph-Enhanced Retrieval (LightRAG-style Navigation Layer)**

不是传统的 GraphRAG（图谱直接生成答案），也不是纯 Vector RAG。知识图谱的角色是**导航层**，引导 Chunk 检索，最终仍以原始文档 Chunk 作为回答依据。

---

## 核心检索链路

系统维护 **四层索引**，查询时按需组合：

```
                   ┌──────────────┐
                   │  Neo4j KG    │  (实体 + 关系)
                   └──────┬───────┘
                          │
     ┌────────────────────┼───────────────────┐
     ▼                    ▼                   ▼
Chunk Index         Entity Index        Relation Index
(Milvus dense)      (Milvus)            (Milvus)
     │                    │                   │
     ▼                    ▼                   ▼
BM25 Index
(rank-bm25)
```

- **Chunk Index**: 文档片段的 dense vector（1024 维 BGE-M3）+ BM25 关键词索引
- **Entity Index**: 实体名称+描述的 dense vector，支持语义检索（如"收购边缘 AI 公司的手机厂商" → Apple）
- **Relation Index**: 关系句子的 dense vector（如 "Apple ACQUIRED Xnor.ai"），支持全局主题检索

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      FastAPI Layer (:8000)                        │
│  POST /api/v1/documents/upload   POST /api/v1/qa/ask             │
│  GET  /api/v1/documents/*        POST /api/v1/qa/stream (SSE)    │
│  GET  /api/v1/system/stats        GET /health                    │
└───────────────────────────┬──────────────────────────────────────┘
                            │
               ┌────────────┴────────────┐
               │   Agent Workflow         │
               │  (LangGraph StateGraph)  │
               └────────────┬────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
    ▼                       ▼                       ▼
Query Router         LightRAG Agent          Retrieval Agent
(intent classify)    (entity+relation        (hybrid search)
    │                 +graph+chunk)              │
    │                       │               ┌────┴────┐
    │                       │               ▼         ▼
    │                       │          Dense Search  BM25
    │                       │          (separate     (separate
    │                       │           queries)      queries)
    │                       │               └────┬────┘
    │                       │                    ▼
    │                       │           RRF Fusion (dense 0.6 + BM25 0.4)
    │                       │                    │
    ▼                       ▼                    ▼
 ┌────────┐          ┌──────────┐         ┌─────────┐
 │chitchat│          │ Answer   │         │ Reranker│
 │  LLM   │          │ Generator│         │         │
 └────────┘          └────┬─────┘         └─────────┘
                          │
                          ▼
                   Answer Validator
                   (structured failure
                    reasons + feedback)
                          │
                          ▼
                 Final Answer + Citations
```

---

## LangGraph 工作流详情

### AgentState（17 个字段）

```python
query: str          # 原始用户问题
query_type: str     # chitchat | simple_fact | multi_hop | comparison | definition
confidence: float   # 分类置信度
graph_eligible: bool  # 多实体+关系词 → 允许图谱增强（兜底路由信号）

documents: list     # 检索到的 chunks（operator.add 累加）
graph_context: str  # 图谱扩展后的格式化上下文
graph_entities: list[str]  # 检索到的相关实体名
sub_queries: list[str]     # 从图谱生成的检索子问题（LightRAG 特性）

retrieval_path: str  # 检索路径说明（可观测性）
draft_answer: str    # 生成答案草稿
final_answer: str    # 最终答案
citations: list      # 引用列表
validation: dict     # 验证结果
validation_feedback: str  # 结构化失败反馈（指导重试）
iteration: int       # 当前迭代次数
max_iterations: int  # 最大迭代次数 (默认 5)
error: str           # 错误信息
folder: str          # 文件夹过滤
tags: list[str]      # 标签过滤
```

### 路由逻辑

```
START → query_router
           │
           ├─ chitchat → chitchat → END
           │
           ├─ holistic → retrieval_agent → answer_generator → answer_validator
           │              (Microsoft GraphRAG 已停用)
           │
           ├─ multi_hop / comparison → lightrag_agent → answer_generator → answer_validator
           │   (LightRAG: entity_index → relation_index → graph_expand → chunk_retrieve)
           │
           ├─ simple_fact / definition + graph_eligible → lightrag_agent → ...
           │   (兜底：多实体 + 关系词的简单事实也走图谱增强)
           │
           └─ simple_fact / definition → retrieval_agent → answer_generator → answer_validator
               (纯检索，不引入图谱噪声)
```

### 验证循环

```
answer_validator ── is_valid=true ──→ END
       │
       │ is_valid=false, iteration < max_iter
       │
       ├─ failure_reason = "context_insufficient"
       │     └─→ retrieval_agent (重新检索)
       │
       └─ failure_reason = "missing_citation" / "unsupported_claim" / "conflict_detected"
             └─→ answer_generator (带结构化反馈修复答案)
```

---

## 模块详解

### 1. 文档解析 (`src/document_parser/`)

| 模块 | 职责 | 技术 |
|------|------|------|
| `mineru_parser.py` | PDF/Office 解析 | MinerU CLI (`.venv/bin/mineru`), ModelScope 源 |
| `ocr_parser.py` | 扫描件/图片 OCR | PaddleOCR-VL-1.5 |
| `table_parser.py` | 表格解析 + 跨页合并 | HTML/Markdown, 表头匹配 |
| `chart_parser.py` | 图表描述生成 | OCR + DeepSeek VLM |
| `langchain_compat.py` | PaddleOCR 兼容补丁 | monkey-patch langchain 旧模块 (必须在 paddleocr import 之前加载) |

### 2. Chunk 切分 (`src/chunker/`)

- **HierarchicalChunker** (`chunk_size=512, overlap=64`):
  - 基于 Markdown H1-H6 标题构建层级树
  - 每个 heading 下使用 `RecursiveCharacterTextSplitter` 按语义边界递归切分
  - 分隔符优先级: `\n\n` → `\n` → `。` → `！` → `？` → `；` → `，` → 字符级
  - 解决了中文文本无法简单 `split()` 的问题
- **TableChunker**: >30 行的大表自动拆分，保留表头
- **ContextMerger**: 相邻同类 chunk 合并 (max 1500 字符)，去重用 `hash(text[:500])`

### 3. Embedding (`src/embeddings/`)

- **BGE-M3**: 本地 FlagEmbedding (GPU) + SiliconFlow API 双路 fallback
- 输出: dense (1024 维) + sparse (lexical weights)
- 最长 8192 tokens
- `encode_dense_all()`: ThreadPoolExecutor 并发批处理 (concurrency=8)，替代串行循环

### 4. 检索系统 (`src/retrieval/`)

#### 4a. 基础检索器

| 模块 | 算法 | 说明 |
|------|------|------|
| `vector_retriever.py` | COSINE + IVF_FLAT | Milvus 密集向量，管理 chunk 集合 |
| `bm25_retriever.py` | Okapi BM25 | jieba 分词，增量追加 (O(1) dedup via `_chunk_ids` set)，约 5-10x 加速 |
| `hybrid_retriever.py` | RRF (k=60) | **dense=0.6, BM25=0.4**，支持分离查询 (dense 保持自然语言，BM25 可增强实体词) |
| `reranker.py` | 三策略 | 1) SiliconFlow rerank API (BGE-reranker-v2-m3) 2) 本地 BGE-M3 cosine 3) TF-IDF fallback |

#### 4b. 关键优化：Dense/BM25 查询分离

```
dense_query = 原始自然语言问题  ← 保持语义完整性
bm25_query  = 原始问题 + 相关实体词  ← 增强关键词命中
```

不把实体词拼到 dense query 末尾，防止改变语义向量方向。

#### 4c. LightRAG 索引层 (`src/retrieval/`)

| 模块 | 说明 |
|------|------|
| `entity_index.py` | 实体向量索引。collectio='lightrag_entities'，embed 实体姓名+描述 |
| `relation_index.py` | 关系向量索引。collection='lightrag_relations'，embed 关系句子 (如 "Apple ACQUIRED Xnor.ai") |
| `lightrag_retriever.py` | LightRAG 核心编排器，3 种模式 (local/global/hybrid) |

**LightRAG 检索流程：**

```
Query → EntityIndex.search(query) → top-k 实体
     → RelationIndex.search(query) → top-k 关系
     → Neo4j get_neighbors (2-hop) → 图谱扩展
     → Entity-enriched BM25 query + Natural dense query
     → Chunk Retrieval (dense + BM25, RRF fusion)
     → Rerank → dedup
```

**与原有 Graph Agent 的关键区别：**

| 维度 | 原 Graph Agent | LightRAG Agent |
|------|---------------|----------------|
| 实体提取 | LLM 调用 (NER) | Entity Index 向量搜索 |
| 输入限制 | 仅从 query 文本提取 | 语义匹配 (query 无需包含实体名) |
| 关系检索 | 无 | Relation Index 单独搜索 |
| 成本 | 每 query 1 次额外 LLM 调用 | 仅向量搜索 (无额外 LLM 调用) |
| 回退策略 | - | 若 LightRAG 索引为空 → 自动回退到 graph_agent+retrieval |

#### 4d. 图谱关系白名单 (`config/settings.py`)

```python
graph_relation_whitelist = [
    "ACQUIRED", "RELATED_TO_TECH", "USED_IN", "AFFECTS",
    "PART_OF", "DEPENDS_ON", "DEVELOPS", "PROVIDES_TECHNOLOGY_FOR",
    "COMPETES_WITH", "INTEGRATED_INTO", "POWERS", "SUPPORTS",
]
# 低权重关系 (跳过): LOCATED_IN, FOUNDED_BY, CEO, HEADQUARTERED_IN, WORKS_FOR, MENTIONS, RELATES_TO
```

查询时，`_filter_relevant_entities` 先用白名单预过滤图谱路径，再交给 LLM 精选实体。减少 token 消耗和噪声。

### 5. 知识图谱 (`src/knowledge_graph/`)

| 模块 | 职责 | 细节 |
|------|------|------|
| `entity_extractor.py` | 实体关系抽取 | DeepSeek LLM few-shot / LangExtract |
| `neo4j_manager.py` | Neo4j CRUD | UNWIND 批量插入 (~50x 加速), `get_neighbors()` 使用 `r.type` property 获取真实关系类型 (非 `type(r)` Neo4j 函数) |
| `graph_query.py` | 图谱查询 | Text-to-Cypher, 实体检索, 路径查询 |

### 5b. Microsoft GraphRAG (`src/knowledge_graph/`)

> **当前状态: 已停用 (DISABLED)**。`holistic` 类型 query 不再路由到 GraphRAG Search，改为走 `retrieval_agent`。
> GraphRAG 节点和边保留在 LangGraph 中以确保编译完整性，但路由不可达。

### 6. Agent 框架 (`src/agents/`)

| 模块 | 职责 | 技术 |
|------|------|------|
| `query_router.py` | 意图分类 | DeepSeek LLM, 返回 query_type + graph_eligible |
| `retrieval_agent.py` | 混合检索 + 重排序 + dedup | 支持分离 dense/bm25 查询, rerank 用原始自然语言 query |
| `graph_agent.py` | 实体提取 + 图谱扩展 + 子问题生成 | LLM NER, Neo4j expand, `generate_sub_questions()` |
| `answer_validator.py` | 幻觉检测 + 结构化失败原因 | 4 类 failure_reasons (见下) |
| `workflow.py` | LangGraph StateGraph 编排 | 8 节点, 5 条条件边, 多轮迭代 |

**Graph Agent 子问题生成** (`generate_sub_questions`):
从图谱实体和关系生成 2-4 个自然语言子问题，用于多 query 检索，而非简单拼接实体名。每个子问题聚焦一个方面，适合语义搜索。

**Answer Validator 结构化失败原因:**

| 原因 | 含义 | 重试策略 |
|------|------|---------|
| `missing_citation` | 缺少来源引用 | → answer_generator (要求加引用) |
| `unsupported_claim` | 包含无依据声明 | → answer_generator (要求只使用上下文信息) |
| `context_insufficient` | 上下文信息不足 | → retrieval_agent (重新检索) |
| `conflict_detected` | 上下文矛盾 | → answer_generator (要求说明矛盾) |

### 7. 存储 (`src/storage/`)

- SQLite (`data/documents.db`): 文档元数据 (文件夹/标签/状态), LLM 自动标签
- `get_doc_ids_by_filter()`: 按 folder/tags 过滤 doc_ids，传给 Milvus expr 过滤

### 8. 评测 (`src/evaluation/`)

- 数据集: 105 条多类型 QA 样本
- 指标: Recall@K, 语义相似度, LLM Judge, 引用准确度, 幻觉评分
- 18 个优先级分层的评估指标 (P1/P2/P3)

---

## 数据流

### 文档导入

```
原始文档 (PDF/Word/Excel/PPT/Image/TXT)
  │
  ├─ [1] MinerU 解析 → Markdown + JSON 结构化
  ├─ [2] Chunk 切分 (HierarchicalChunker + TableChunker + ContextMerger)
  ├─ [3] BGE-M3 Embedding → dense (1024维) + sparse
  ├─ [4] Milvus 向量索引 + BM25 关键词索引
  └─ [5] 实体关系抽取 → Neo4j UNWIND 批量导入
       └─→ build_lightrag_index.py → Entity Index + Relation Index (Milvus)
```

### 问答推理 (当前主路径)

```
用户查询
  │
  ├─ query_router: LLM 意图分类
  │
  ├─ chitchat → 直接 LLM 回答
  │
  ├─ simple_fact / definition (无 graph_eligible):
  │     retrieval_agent ── dense(query) ──► Milvus
  │                     ── bm25(query) ──► BM25
  │                     ── RRF fusion ──► rerank ──► dedup
  │                     ──► answer_generator ──► answer_validator
  │
  └─ multi_hop / comparison / simple_fact+graph_eligible:
        lightrag_agent ── entity_index.search ──► top-k 实体
                       ── relation_index.search ──► top-k 关系
                       ── Neo4j expand ──► 图谱邻居
                       ── entity-enriched bm25 + natural dense
                       ── chunk retrieval + rerank + dedup
                       ──► answer_generator ──► answer_validator
```

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/documents/upload` | 上传文档，触发全流程处理 |
| GET | `/api/v1/documents/status/{id}` | 查询处理状态 |
| GET | `/api/v1/documents/` | 文档列表 (支持 folder/tags 过滤) |
| DELETE | `/api/v1/documents/{id}` | 删除文档及关联数据 |
| POST | `/api/v1/qa/ask` | 问答接口 |
| POST | `/api/v1/qa/stream` | SSE 流式问答 |
| GET | `/api/v1/system/stats` | 系统统计 (Milvus/Neo4j/SQLite) |
| GET | `/health` | 健康检查 |

---

## 部署架构

```
┌─────────────────────────────────────────────────┐
│                    服务器                        │
│  ┌──────────────┐  ┌──────────────┐             │
│  │ FastAPI       │  │ React 前端    │            │
│  │ :8000         │  │ :3000        │            │
│  └──────┬────────┘  └──────────────┘            │
│         │                                        │
│  ┌──────┴───────────────────────────┐           │
│  │         外部服务                  │           │
│  │  ┌───────┐ ┌───────┐ ┌───────┐  │           │
│  │  │ Milvus│ │ Neo4j │ │DeepSeek│ │           │
│  │  │:19530 │ │:7687  │ │  API  │ │           │
│  │  └───────┘ └───────┘ └───────┘  │           │
│  │  ┌───────────┐                  │           │
│  │  │SiliconFlow│                  │           │
│  │  │BGE-M3 API │                  │           │
│  │  └───────────┘                  │           │
│  └────────────────────────────────┘            │
│  ┌─────────────────────────────────┐           │
│  │        GPU (可选)               │           │
│  │  PaddleOCR-VL (文档 OCR)       │           │
│  │  BGE-M3 本地推理 (备选)        │           │
│  └─────────────────────────────────┘          │
└─────────────────────────────────────────────────┘
```

---

## 目录结构

```
agentic-rag/
├── config/
│   ├── settings.py            # pydantic-settings, 加载 .env
│   └── prompts.py             # 全部 LLM prompt 模板
├── src/
│   ├── document_parser/       # 文档解析 (MinerU, PaddleOCR-VL, 表格/图表)
│   ├── chunker/               # Chunk 切分 + 合并 + 去重
│   ├── embeddings/            # BGE-M3 嵌入 (API + 本地 GPU 双路)
│   ├── retrieval/             # 检索系统
│   │   ├── vector_retriever.py    # Milvus chunk 向量检索
│   │   ├── bm25_retriever.py      # BM25 关键词检索
│   │   ├── hybrid_retriever.py    # RRF 混合检索 (支持分离 dense/bm25 查询)
│   │   ├── reranker.py            # 多策略重排序
│   │   ├── graph_expander.py      # Neo4j 图谱路径扩展
│   │   ├── entity_index.py        # LightRAG 实体向量索引
│   │   ├── relation_index.py      # LightRAG 关系向量索引
│   │   └── lightrag_retriever.py  # LightRAG 编排器
│   ├── knowledge_graph/       # 知识图谱
│   │   ├── entity_extractor.py    # LLM 实体关系抽取
│   │   ├── neo4j_manager.py       # Neo4j CRUD + 批量导入
│   │   ├── graph_query.py         # Text-to-Cypher + 图谱查询
│   │   ├── graphrag_indexer.py    # [已停用] MS GraphRAG 索引
│   │   └── graphrag_query.py      # [已停用] MS GraphRAG 搜索
│   ├── llm/                   # DeepSeek LLM 封装
│   ├── agents/                # Agent 框架
│   │   ├── query_router.py        # 意图分类 + graph_eligible 检测
│   │   ├── retrieval_agent.py     # 检索编排 + dedup
│   │   ├── graph_agent.py         # 实体提取 + 图谱扩展 + 子问题生成
│   │   ├── answer_validator.py    # 幻觉检测 + 结构化失败原因
│   │   └── workflow.py            # LangGraph StateGraph 工作流
│   └── evaluation/            # 评测体系
├── api/                       # FastAPI 路由
│   ├── main.py
│   ├── schemas.py
│   └── routes/
│       ├── documents.py       # 文档 CRUD
│       ├── qa.py              # 问答案 /ask + /stream
│       ├── management.py      # 系统统计 / 索引重建
│       └── evaluation.py      # 评测接口
├── scripts/
│   ├── ingest_documents.py    # 文档导入
│   ├── build_graph.py         # 构建 Neo4j 知识图谱
│   ├── build_graphrag.py      # 构建 MS GraphRAG 索引 [已停用]
│   ├── build_lightrag_index.py # 构建 LightRAG 实体+关系向量索引
│   └── run_evaluation.py      # 运行评测
├── tests/                     # 测试
├── frontend/                  # React 前端 (Vite + Tailwind + shadcn/ui)
└── data/
    ├── raw/                   # 原始文档
    ├── processed/             # MinerU 处理输出
    ├── documents.db           # SQLite 文档元数据
    ├── bm25_index/            # BM25 持久化索引
    └── graphrag/              # MS GraphRAG 数据 [已停用]
```

---

## 已完成的优化

| 优化 | 文件 | 效果 |
|------|------|------|
| Neo4j UNWIND 批量插入 | `neo4j_manager.py:66-102` | ~50x 加速 |
| BM25 增量追加 | `bm25_retriever.py:36-44` | ~5-10x 加速 |
| Dense/BM25 查询分离 | `hybrid_retriever.py:31-57`, `workflow.py:209-249` | 语义检索不受实体词干扰 |
| Embedding 并发批处理 | `bge_m3.py:54-70` | ~3-5x 加速 |
| 图谱关系白名单 | `settings.py:63-69`, `workflow.py:251-291` | 减少低权重关系噪声 |
| Chunk 去重安全化 | `context_merger.py:41` | hash(text[:500]) 替代 text[:100] |
| Validator 结构化失败原因 | `prompts.py:97-114`, `answer_validator.py`, `workflow.py:73-83,398-442` | 按原因重试，不盲目烧 token |
| Query Router 兜底 | `prompts.py:16-20`, `query_router.py`, `workflow.py:41-54` | graph_eligible 信号防止误分类 |
| Graph Agent 子问题生成 | `graph_agent.py:70-101`, `workflow.py:213-232` | 多 query 检索替代实体拼接 |
| RRF 权重优化 | `settings.py:56-58` | dense 0.5→0.6, BM25 0.2→0.4 |
| Neo4j type(r) bugfix | `neo4j_manager.py:113,143` | r.type property 替代 type(r) 函数，获取真实关系谓词 |

---

## 启动命令

```bash
# 后端
uv run -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend && npm run dev

# 构建 LightRAG 索引 (需先有 Neo4j 数据)
uv run python scripts/build_lightrag_index.py

# 安全测试 (无需外部服务)
uv run -m pytest tests/test_parser.py tests/test_chunker.py tests/test_graph.py -v
```

---

## 外部服务依赖

| 服务 | 端口 | 用途 |
|------|------|------|
| Milvus Standalone | 19530 | Chunk 向量检索 + Entity/Relation 向量索引 |
| Neo4j | 7687 (bolt) | 知识图谱存储 + 路径扩展 |
| DeepSeek API | remote | LLM 推理 (分类/生成/验证) |
| SiliconFlow API | remote | BGE-M3 Embedding + BGE Reranker |
