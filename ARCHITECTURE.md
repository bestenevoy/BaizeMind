# Agentic-GraphRAG 架构文档

## 定位

> **Hybrid RAG + Graph-Enhanced Retrieval (LightRAG-style Navigation Layer)**

知识图谱的角色是**导航层**（非直接答案来源），引导 Chunk 检索，最终仍以原始文档 Chunk 作为回答依据。不是传统 GraphRAG（图谱直接生成答案），也不是纯 Vector RAG。

---

## 四层索引体系

系统维护四层索引，查询时按需组合：

```
                    ┌──────────────┐
                    │  Neo4j KG    │  (实体 + 关系)
                    └──────┬───────┘
                           │
      ┌────────────────────┼───────────────────┐
      ▼                    ▼                   ▼
Chunk Index          Entity Index         Relation Index
(Milvus dense)       (Milvus dense)       (Milvus dense)
      │                    │                   │
      ▼                    ▼                   ▼
BM25 Index            (LightRAG 层)       (LightRAG 层)
(rank-bm25)
```

| 索引层 | 存储 | 维度 | 用途 |
|-------|------|------|------|
| Chunk Index | Milvus `agentic_rag` + `rank_bm25.BM25Okapi` | 1024 | 文档片段的 dense + 关键词检索 |
| Entity Index | Milvus `lightrag_entities` | BGE-M3 dim | 实体语义匹配，如"收购边缘 AI 公司的手机厂商" → Apple |
| Relation Index | Milvus `lightrag_relations` | BGE-M3 dim | 关系语义匹配，如 "Apple ACQUIRED Xnor.ai" |
| Neo4j KG | Neo4j bolt://7687 | — | 图遍历 / 2-hop 邻居 / 最短路径 |

---

## 系统架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                     FastAPI Layer (:8000)                             │
│  POST /api/v1/documents/upload    POST /api/v1/qa/ask               │
│  GET  /api/v1/documents/*         POST /api/v1/qa/stream (SSE)      │
│  GET  /api/v1/system/*            GET /api/v1/evaluation/*          │
│  GET  /health                                                         │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │   Agent Workflow       │
                │  (LangGraph StateGraph) │
                └───────────┬───────────┘
                            │
    ┌───────────────────────┼───────────────────────────┐
    │                       │                           │
    ▼                       ▼                           ▼
Query Router           LightRAG Agent              Retrieval Agent
(LLM 意图分类)       (entity → relation         (hybrid search)
    │                  → graph → chunk)              │
    │                       │                   ┌────┴─────┐
    │     ┌─────────────────┘                   ▼          ▼
    │     │ fallback (LightRAG index 为空时): Dense Search  BM25
    │     │   graph_agent → retrieval_agent    (Milvus)    (jieba)
    │     │                                       └────┬─────┘
    ▼     ▼                                            ▼
  ┌────────┐  ┌──────────┐                     RRF Fusion
  │chitchat│  │  Answer  │                (dense 0.6 + BM25 0.4)
  │  LLM   │  │ Generator│                          │
  └────────┘  └────┬─────┘                     ┌─────┴─────┐
                   │                           ▼           ▼
                   ▼                       Reranker      Dedup
            Answer Validator          (SiliconFlow/   (chunk_id)
            (结构化失败原因)            local/TF-IDF)
                   │
                   ▼
          Final Answer + Citations
```

---

## LangGraph 工作流详情

### AgentState（21 字段）

```python
query: str              # 原始用户问题
query_type: str         # chitchat | simple_fact | multi_hop | comparison | definition | sql_query
confidence: float       # 分类置信度 0.0-1.0
graph_eligible: bool    # 多实体+关系词 → 允许图谱增强

documents: list[dict]   # 检索到的 chunks (Annotated[list, operator.add])
graph_context: str      # 图谱扩展后的格式化文本
graph_entities: list[str]   # 相关实体名
sub_queries: list[str]      # LightRAG/graph_agent 生成的检索子问题
graphrag_context: str       # MS GraphRAG 结果 (unreachable)

retrieval_path: str     # 检索路径说明（可观测性）
draft_answer: str       # 答案草稿
final_answer: str       # 最终答案
citations: list[str]    # 引用 doc_id_chunk_id 列表
validation: dict        # 验证结果
validation_feedback: str    # 结构化失败反馈

iteration: int          # 当前迭代
max_iterations: int     # 最大迭代 (默认 5)
error: str              # 错误信息
folder: str             # 文件夹过滤
tags: list[str]         # 标签过滤

# Excel 强制路由相关
force_sql: bool         # folder/tags 过滤后文档全为 .xlsx/.xls → 强制走 sql_agent 且失败不 fallback
rerouted_to_sql: bool   # 自动重判防死循环：validator → sql_agent 重试后置 True
```

### 节点 (9 个)

| 节点 | 职责 |
|------|------|
| `query_router` | LLM 意图分类：query_type + confidence + graph_eligible；force_sql=True 时覆盖为 sql_query（chitchat 例外） |
| `chitchat` | 直接 LLM 回答，无检索，立即终止 |
| `sql_agent` | Excel NL2SQL 检索：向量召回 Sheet → 多表选择 → NL2SQL → 执行（含重试）；force_sql=False 且无 sheet 时 fallback 到 retrieval_agent |
| `retrieval_agent` | Hybrid (dense + BM25) → RRF fusion → rerank → dedup |
| `graph_agent` | LLM NER → Neo4j expand → 子问题生成 → 实体富化 BM25 → retrieval_agent |
| `lightrag_agent` | Entity Index + Relation Index → Neo4j expand → chunk retrieve（含 fallback） |
| `graphrag_search` | **[UNREACHABLE]** MS GraphRAG global/local/drift search |
| `answer_generator` | LLM 用检索上下文 + 图谱上下文生成答案 + 引用 |
| `answer_validator` | 幻觉检测 + 结构化失败原因 + 循环重试 + excel_sheet 重判到 sql_agent |

### 边

| 类型 | 源 → 目标 | 条件 |
|------|-----------|------|
| 固定 | START → query_router | — |
| 固定 | chitchat → END | — |
| 固定 | sql_agent → answer_generator | — |
| 固定 | retrieval_agent → answer_generator | — |
| 固定 | lightrag_agent → answer_generator | — |
| 固定 | answer_generator → answer_validator | — |
| 条件 | query_router → chitchat / sql_agent / retrieval_agent / lightrag_agent | `_route_by_query_type` |
| 条件 | graph_agent → retrieval_agent | `_route_for_multi_hop`（无条件路由到 retrieval） |
| 条件 | graphrag_search → ... | `_route_after_graphrag` [UNREACHABLE] |
| 条件 | answer_validator → END / retrieval_agent / answer_generator / sql_agent | `_route_after_validation` |

### 路由逻辑（`_route_by_query_type` + force_sql）

```
┌────────────────────────────────────────────────────────────────────────┐
│ workflow.invoke(query, folder, tags)                                   │
│   force_sql = _should_force_sql(folder, tags)                          │
│   # folder/tags 过滤后文档全为 .xlsx/.xls → force_sql=True             │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
                            query_router
                                   │
       ┌───────────┬───────────────┼─────────────┬──────────────┐
       ▼           ▼               ▼             ▼              ▼
   chitchat     sql_agent     retrieval      lightrag        (其他)
   → END         │           _agent          _agent
                 │               │             │
       ┌─────────┘               │             │
       │ force_sql=True             │             │
       │ 且 no_sheets 时            │             │
       │ 不 fallback                │             │
       ▼                           ▼             ▼
   ┌──────────┐              answer_generator
   │ NL2SQL   │  no_sheets      ↑
   │ + 执行   │  + 非 force  ────┘
   └────┬─────┘  → fallback
        │
        ▼
   answer_generator → answer_validator
                            │
                            ▼
                   (见验证循环图)
```

详细分支：

```
query_router
  │
  ├─ chitchat ⇒ chitchat → END
  │
  ├─ sql_query (含 force_sql=True 强制覆盖，chitchat 例外)
  │   ⇒ sql_agent → answer_generator → answer_validator → END/(loop)
  │   │
  │   └─ sql_agent 内部:
  │      ├─ force_sql=True + 召回失败 → 返回空 documents（不 fallback，answer_generator 看到"无数据"信号）
  │      ├─ force_sql=False + 召回失败 → fallback 到 retrieval_agent（文本 RAG）
  │      └─ 召回成功 → NL2SQL + 执行（含重试）→ SQL 结果作为 document 注入
  │
  ├─ holistic ⇒ retrieval_agent → answer_generator → answer_validator → END/(loop)
  │   (MS GraphRAG 已停用，改为走普通检索)
  │
  ├─ multi_hop / comparison / (simple_fact|definition + graph_eligible=True)
  │   ⇒ lightrag_agent → answer_generator → answer_validator → END/(loop)
  │   │
  │   └─ lightrag_agent 内部:
  │      ├─ LightRAG entity index 有数据 → Entity Index → Relation Index → Graph Expand → Chunk Retrieve
  │      └─ entity index 为空 (.count() == 0) → fallback: graph_agent → retrieval_agent
  │
  └─ simple_fact / definition (graph_eligible=False)
      ⇒ retrieval_agent → answer_generator → answer_validator → END/(loop)
```

**关键变更**：
- `multi_hop` / `comparison` 的主路径是 `lightrag_agent`（而非 `graph_agent`）。`lightrag_agent` 在 LightRAG 索引为空时自动 fallback 到 `graph_agent → retrieval_agent` 路径，保证可用性。
- `force_sql=True` 时 query_router 强制覆盖为 sql_query，且 sql_agent 失败不 fallback（用户明确选了 Excel 文件）。
- `force_sql` 由 `_should_force_sql(folder, tags)` 自动判断：folder/tags 过滤后文档全为 .xlsx/.xls → True；含其他类型文档 → False。

### 验证循环（`_route_after_validation`）

```
answer_validator
  │
  ├─ rerouted_to_sql=True 且 is_valid=false  → END  (★ 死循环防护，见下)
  │
  ├─ is_valid=true 或 iteration >= max_iterations  → END
  │
  └─ is_valid=false 且 iteration < max_iterations 且 rerouted_to_sql=False:
       │
       ├─ failure_reason 含 "context_insufficient":
       │   │
       │   ├─ 检索到 excel_sheet 类型的 chunk（metadata.source="excel_sheet" 或 chunk_id 前缀 "excel:"）
       │   │   OR 回答文本含"信息不足"短语（兜底 validator 误判 is_valid=true 的场景）
       │   │   → sql_agent（自动重判走 NL2SQL 拿真实数据）
       │   │   └─ sql_agent 返回时设置 rerouted_to_sql=True，防再次进 sql_agent
       │   │
       │   └─ 其他情况
       │       → retrieval_agent（重新检索）
       │
       └─ failure_reason 为 missing_citation / unsupported_claim / conflict_detected
           → answer_generator（带结构化反馈修复）
```

**重判触发条件**（自动从 doc rag 切换到 nl2sql）：
1. `answer_validator` 标 `context_insufficient`，**OR** 回答文本含"信息不足"短语（兜底 validator 误判 is_valid=true 的场景）
2. 检索 documents 中存在 `metadata.source == "excel_sheet"` 的 chunk（之前 doc rag 检索到了 sheet 摘要 chunk）
3. `rerouted_to_sql=False`（尚未重判过，防死循环）
4. `iteration < max_iterations`

重判后 sql_agent 返回的 SQL 执行结果与之前的 sheet 摘要 chunk **累加**（LangGraph `operator.add`），answer_generator 看到"sheet 摘要 + 真实 SQL 结果"双重信息生成更准确的回答。

**★ 死循环防护**（`rerouted_to_sql=True` 的双重作用）：
- **第一次保护**：阻止 `sql_agent → validator → sql_agent` 循环（rerouted_to_sql=True 时不再触发重判条件）
- **第二次保护**：阻止 `retrieval_agent → validator → retrieval_agent` 空转循环（rerouted_to_sql=True + is_valid=false 时直接 END，不再走 retrieval_agent）
- **理由**：此时已穷尽 doc rag + nl2sql 两条路径，同一文档库再走 retrieval 也不会有新信息，继续烧 token 无意义

### 验证失败原因

| 原因 | 含义 | 重试策略 |
|------|------|---------|
| `missing_citation` | 缺少来源引用 | → answer_generator（要求加引用） |
| `unsupported_claim` | 包含无依据声明 | → answer_generator（要求只用上下文信息） |
| `context_insufficient` | 上下文信息不足 | → retrieval_agent（重新检索）；或 → sql_agent（重判，见上） |
| `conflict_detected` | 上下文矛盾 | → answer_generator（要求说明矛盾） |

---

## 模块详解

### 1. 文档解析 (`src/document_parser/`)

| 文件 | 职责 | 技术细节 |
|------|------|---------|
| `mineru_parser.py` | PDF/Office 解析 | MinerU CLI (`.venv/bin/mineru`, 通过 `sys.executable.parent` 自动解析), ModelScope 源 |
| `ocr_parser.py` | 扫描件/图片 OCR | PaddleOCR-VL-1.5 (`./PaddleOCR-VL-1.5/PaddlePaddle/PaddleOCR-VL-1.5`) |
| `table_parser.py` | 表格解析 + 跨页合并 | HTML/Markdown，表头匹配 |
| `chart_parser.py` | 图表描述生成 | DeepSeek VLM (vision model) |
| `langchain_compat.py` | PaddleOCR 兼容 | monkey-patch 已删除的 langchain 模块（`langchain_community.document_loaders` → `langchain_core` 等），**必须在 paddleocr import 之前加载** |

**重要**：MinerU CLI 不在系统 PATH 中，`mineru_parser.py` 通过 `sys.executable.parent` 自动定位 `.venv/bin/mineru`，不可直接用裸命令。

### 2. Chunk 切分 (`src/chunker/`)

| 文件 | 职责 | 技术细节 |
|------|------|---------|
| `hierarchical_chunker.py` | 层级切分 | `chunk_size=512, overlap=64`；基于 Markdown H1-H6 标题构建层级树；每个 heading 下用 `RecursiveCharacterTextSplitter` 按语义边界递归切分，分隔符优先级: `\n\n` → `\n` → `。` → `！` → `？` → `；` → `，` → 字符级 |
| `table_chunker.py` | 大表拆分 | >30 行表格自动拆分，保留表头 |
| `context_merger.py` | 合并去重 | 相邻同类 chunk 合并 (max 1500 字符)，去重用 `hash(text[:500])` |

### 3. Embedding (`src/embeddings/`)

| 文件 | 职责 | 技术细节 |
|------|------|---------|
| `bge_m3.py` | BGE-M3 embedding | 本地 FlagEmbedding (GPU) + SiliconFlow API 双路；输出 dense (1024 维) + sparse (lexical weights)；最大 8192 tokens；`encode_dense_all()` 用 `ThreadPoolExecutor` 并发批处理 (concurrency=8)，替代串行循环 |

默认使用 SiliconFlow API (`BGE_M3_USE_LOCAL=false`)。本地模式需 GPU + 下载 `BAAI/bge-m3` 模型。

### 4. 检索系统 (`src/retrieval/`)

#### 4a. 基础检索器

| 文件 | 类名 | 算法 | 技术细节 |
|------|------|------|---------|
| `vector_retriever.py` | `MilvusVectorRetriever` | COSINE + IVF_FLAT | Milvus dense vector 搜索，chunk collection `agentic_rag`；`nlist=128`, `nprobe=16`；支持 `doc_id` filter expression |
| `bm25_retriever.py` | `BM25Retriever` | Okapi BM25 | `rank_bm25.BM25Okapi`, jieba 中文分词（fallback: `str.lower().split()`）；增量追加 via `_chunk_ids` set (O(1) dedup)；pickle 持久化到 `data/bm25_index/` |
| `hybrid_retriever.py` | `HybridRetriever` | RRF | **dense=0.6, BM25=0.4, rrf_k=60**；支持分离 dense/bm25 查询；`retrieval_similarity_threshold` 过滤 (默认 0.0 = 禁用) |
| `reranker.py` | `Reranker` | 三策略 | 见下 |
| `graph_expander.py` | `GraphExpander` | 图遍历 | Neo4j `get_neighbors()` 2-hop 扩展，去重 by `path_string` |

#### 4b. Dense/BM25 查询分离

```
dense_query = 原始自然语言问题         ← 保持语义完整性
bm25_query  = 原始问题 + 实体名（最多10个） ← 增强关键词命中
```

实体名不拼到 dense query 末尾，防止改变语义向量方向。

#### 4c. Reranker 三策略

| 方法 | `settings.reranker_method` | 实现 |
|------|--------------------------|------|
| Cross-Encoder | `"embedding"` (默认) | SiliconFlow BGE-reranker-v2-m3 API → fallback 本地 BGE-M3 cosine → fallback TF-IDF |
| LLM Listwise | `"llm"` | DeepSeek LLM 列表重排序 (JSON 索引输出) → fallback TF-IDF |
| Hybrid | `"hybrid"` | Embedding 取 top_k×2 → LLM 精选 final top_k |

#### 4d. LightRAG 层

| 文件 | 类名 | 职责 | Collection |
|------|------|------|-----------|
| `entity_index.py` | `EntityIndex` | 实体向量索引 | `lightrag_entities` |
| `relation_index.py` | `RelationIndex` | 关系向量索引 | `lightrag_relations` |
| `lightrag_retriever.py` | `LightRAGRetriever` | 编排器，3 种模式 (local/global/hybrid) | — |

**LightRAG 检索流程:**

```
Query → EntityIndex.search(query, top_k=10) → top-k 实体 (按名称+描述匹配)
     → RelationIndex.search(query, top_k=10) → top-k 关系 (按 "S P O" 匹配)
     → Neo4j get_neighbors (2-hop) → 图谱扩展
     → Entity-enriched BM25 query + Natural dense query
     → Hybrid Retriever (dense + BM25, RRF fusion)
     → Rerank → dedup by chunk_id
```

**三种检索模式 (`settings.lightrag_retrieval_mode`):**

| 模式 | 实体索引 | 关系索引 | 图谱扩展 | 适用场景 |
|------|---------|---------|---------|---------|
| `local` | 搜索 top-5 实体 | 不用 | 实体 2-hop | 查询聚焦特定实体 |
| `global` | 不用 | 搜索 top-k 关系 | 关系主体 1-hop | 查询聚焦主题/模式 |
| `hybrid` (默认) | 搜索 top-5 实体 | 搜索 top-k 关系 | 两者合并 | 通用 |

**Fallback 机制**：`lightrag_agent` 在 entity index `.count() == 0` 时自动回退到 `graph_agent → retrieval_agent`，确保无 LightRAG 索引时也能正常工作。

### 5. 知识图谱 (`src/knowledge_graph/`)

| 文件 | 类名 | 职责 | 技术细节 |
|------|------|------|---------|
| `entity_extractor.py` | `EntityExtractor` | 实体关系抽取 | DeepSeek LLM few-shot (`ENTITY_RELATION_SYSTEM` + `ENTITY_RELATION_EXAMPLE`); 可选 LangExtract library (`use_langextract=False`) |
| `neo4j_manager.py` | `Neo4jManager` | Neo4j CRUD | **UNWIND 批量插入** (~50x 加速)；`get_neighbors()` 用 `r.type` property 获取真实关系类型 (不用 `type(r)` Neo4j 函数)；`find_paths()` 最短路径 (case-insensitive) |
| `graph_query.py` | `GraphQuery` | 自然语言查图 | LLM Text-to-Cypher (`TEXT_TO_CYPHER_SYSTEM`); `search_by_entity_name()` case-insensitive |
| `graphrag_indexer.py` | `GraphRAGIndexer` | MS GraphRAG 索引 | 通过 subprocess 调用 `graphrag init/index` CLI；DeepSeek chat + SiliconFlow embedding |
| `graphrag_query.py` | `GraphRAGQuery` | MS GraphRAG 查询 | Global/Local/DRIFT 三种搜索；LanceDB vector stores；Parquet 数据源 |

#### 5a. Neo4j UNWIND 批量插入

```python
# 所有实体的单次 UNWIND 查询（1 次网络往返）
UNWIND $entities AS e
MERGE (n:Entity {name: e.name})
SET n.type = e.type, n.description = e.description, n.doc_id = $doc_id

# 所有关系的单次 UNWIND 查询（1 次网络往返）
UNWIND $relations AS r
MATCH (s:Entity {name: r.subject})
MATCH (o:Entity {name: r.object})
MERGE (s)-[rel:RELATES_TO {type: r.predicate}]->(o)
```

#### 5b. Microsoft GraphRAG

> **当前状态**: 索引和查询功能完整实现，但 LangGraph 工作流中 `graphrag_search` 节点 **不可达**（`_route_by_query_type` 将 `holistic` 路由到 `retrieval_agent`，`_route_for_multi_hop` 无到此节点的路径）。节点和边保留以确保 StateGraph 编译完整性。

CLI 可用: `uv run python scripts/build_graphrag.py`

### 6. 图谱关系过滤

**白名单** (`config/settings.py`):

```python
graph_relation_whitelist = [
    "ACQUIRED", "RELATED_TO_TECH", "USED_IN", "AFFECTS",
    "PART_OF", "DEPENDS_ON", "DEVELOPS", "PROVIDES_TECHNOLOGY_FOR",
    "COMPETES_WITH", "INTEGRATED_INTO", "POWERS", "SUPPORTS",
]
# 低权重（跳过，除非无白名单命中）:
# LOCATED_IN, FOUNDED_BY, CEO, HEADQUARTERED_IN, WORKS_FOR, MENTIONS, RELATES_TO
```

`_filter_relevant_entities()` 先用白名单预过滤图谱路径，再交给 LLM 精选实体，减少 token 消耗和噪声。

### 7. LLM 层 (`src/llm/`)

| 函数 | 模型 | 用途 |
|------|------|------|
| `get_chat_llm(temperature, model)` | `deepseek-v4-flash` (默认) | 意图分类 / 答案生成 / 实体抽取 / 验证 |
| `get_reasoner_llm(temperature)` | `deepseek-v4-pro` | 推理任务（预留） |

基于 LangChain `ChatOpenAI`，兼容 OpenAI API。

### 8. 存储 (`src/storage/`)

| 文件 | 职责 | 技术细节 |
|------|------|---------|
| `doc_store.py` | SQLite 文档元数据 | `data/documents.db`，表 `documents` (17 列) + `folder_markers`；WAL 模式；支持 folder/tags/status 过滤；folder 层级管理（创建/删除/移动） |
| `auto_tagger.py` | LLM 自动标签 | 根据文档内容自动分配标签 |
| `config_overrides.py` | 运行时配置覆盖 | JSON 持久化的配置覆盖机制 |

`get_doc_ids_by_filter()` 用于检索阶段的文件夹/标签过滤 → Milvus `doc_id in [...]` filter。

### 9. Agent 工具 (`src/agents/tools.py`)

独立的 LangChain `@tool` 函数集，**不在主工作流中使用**，为备选 tool-calling Agent 路径预留：

| 工具 | 功能 |
|------|------|
| `hybrid_search(query, top_k=10)` | Hybrid dense+BM25 搜索 |
| `bm25_search(query, top_k=10)` | BM25 关键词搜索 |
| `rerank_results(query, results, top_k=5)` | 重排序 |
| `query_kg(question)` | Text-to-Cypher 图谱查询 |
| `expand_path(entity_name, max_hops=2)` | 图谱路径扩展 |
| `get_entity_info(name)` | 实体详情获取 |

GraphRAG 工具 (`graphrag_global_search`, `graphrag_local_search`, `graphrag_drift_search`) 已注释移除。

### 10. 评测 (`src/evaluation/`)

| 文件 | 职责 | 技术细节 |
|------|------|---------|
| `dataset.py` | 数据集管理 | 105 条多类型 QA 样本 (JSON)，支持 CRUD / 导入导出 |
| `runner.py` | 评测执行器 | 运行 LangGraph workflow 对每条样本，计算指标 |
| `metrics.py` | 指标计算 | Recall@K, 语义相似度, LLM Judge, 引用准确度, 幻觉评分 |

评测接口 (`/api/v1/evaluation`) 支持：
- 数据集增删改查、批量导入导出
- **LLM 自动生成 QA 对**（从文档 chunks）
- 运行评测并保存结果
- 结果浏览

---

## 数据流

### 文档导入

```
原始文档 (PDF/Word/Excel/PPT/Image/TXT)
  │
  ├─ [1] MinerU 解析 → Markdown + JSON 结构化 (data/processed/)
  ├─ [2] Chunk 切分 (HierarchicalChunker + TableChunker + ContextMerger)
  ├─ [3] BGE-M3 Embedding → dense (1024维) + sparse
  ├─ [4] Milvus 向量索引 (agentic_rag) + BM25 关键词索引 (data/bm25_index/)
  ├─ [5] 实体关系抽取 → Neo4j UNWIND 批量导入
  ├─ [6] LLM 自动标签 → SQLite (data/documents.db)
  └─ [7] build_lightrag_index.py → Entity Index + Relation Index (Milvus)
```

### 问答推理（当前路径）

```
用户查询
  │
  ├─ query_router: LLM 意图分类 (5 种类型 + graph_eligible)
  │
  ├─ chitchat → 直接 LLM 回答 → END
  │
  ├─ holistic → retrieval_agent → answer_generator → answer_validator → END/(loop)
  │
  ├─ simple_fact / definition (无 graph_eligible):
  │     retrieval_agent
  │       ├─ dense(query) → Milvus (COSINE, nprobe=16)
  │       ├─ bm25(query) → BM25 (jieba, BM25Okapi)
  │       ├─ RRF fusion (dense=0.6, BM25=0.4, k=60)
  │       ├─ Rerank (SiliconFlow cross-encoder → local cosine → TF-IDF fallback)
  │       └─ Dedup by chunk_id
  │     → answer_generator → answer_validator
  │
  └─ multi_hop / comparison / graph_eligible:
        lightrag_agent
          ├─ LightRAG 索引有数据:
          │   ├─ EntityIndex.search(query, top_k=10) → 语义匹配实体
          │   ├─ RelationIndex.search(query, top_k=10) → 语义匹配关系
          │   ├─ Neo4j get_neighbors (2-hop) → 图谱扩展
          │   ├─ Entity-enriched BM25 + Natural dense query
          │   ├─ Hybrid retrieve (dense + BM25, RRF fusion)
          │   └─ Rerank + dedup
          │
          └─ LightRAG 索引为空 (fallback):
              graph_agent
                ├─ LLM NER → extract_entities_from_query
                ├─ Neo4j get_neighbors (2-hop) → 图谱路径
                ├─ _filter_relevant_entities (白名单 + LLM 精选)
                ├─ generate_sub_questions (2-4 个自然语言子问题)
                └─ → retrieval_agent
                      ├─ 对每个 sub_query + 原始 query 执行 hybrid search
                      ├─ 按 chunk_id 去重，最多 20 结果
                      └─ → answer_generator → answer_validator
```

---

## API 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/documents/upload` | 上传文档，触发全流程处理 |
| `GET` | `/api/v1/documents/list` | 文档列表 (folder/tags/status 过滤) |
| `GET` | `/api/v1/documents/{id}/status` | 查询处理状态 |
| `GET` | `/api/v1/documents/{id}/chunks` | 获取文档 Chunks |
| `GET` | `/api/v1/documents/{id}/content` | 获取文档 Markdown 内容 |
| `DELETE` | `/api/v1/documents/{id}` | 级联删除 (Milvus + BM25 + Neo4j + SQLite) |
| `PUT` | `/api/v1/documents/{id}/move` | 移动文档到文件夹 |
| `POST` | `/api/v1/documents/{id}/tags` | 设置标签 |
| `POST` | `/api/v1/documents/{id}/retry` | 重新处理失败文档 |
| `GET/POST/DELETE` | `/api/v1/documents/folders/*` | 文件夹管理 |
| `POST` | `/api/v1/qa/ask` | 问答 (非流式) |
| `POST` | `/api/v1/qa/stream` | 问答 (SSE 流式) |
| `GET` | `/api/v1/system/config` | 系统配置查看 |
| `GET` | `/api/v1/system/connectivity-check` | 外部服务连通性检查 |
| `GET` | `/api/v1/system/stats` | 系统统计 |
| `POST` | `/api/v1/system/cleanup-orphans` | 清理孤儿数据 |
| `GET` | `/api/v1/system/graph/overview` | 图谱可视化数据 |
| `GET` | `/api/v1/system/graph/entity/{name}` | 实体详情 |
| `GET/PUT/DELETE` | `/api/v1/system/config/editable/*` | 运行时配置覆盖 |
| `*` | `/api/v1/evaluation/*` | 评测数据集 + 运行 |
| `GET` | `/health` | 健康检查 |

---

## 配置参数总览

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `deepseek_chat_model` | `deepseek-v4-flash` | 对话 / 分类 / 生成模型 |
| `deepseek_reasoner_model` | `deepseek-v4-pro` | 推理模型 (预留) |
| `siliconflow_embedding_model` | `BAAI/bge-m3` | Embedding 模型 |
| `siliconflow_rerank_model` | `BAAI/bge-reranker-v2-m3` | Reranker 模型 |
| `chunk_size` | 512 | 切分窗口 |
| `chunk_overlap` | 64 | 重叠窗口 |
| `hybrid_dense_weight` | 0.6 | RRF dense 权重 |
| `hybrid_bm25_weight` | 0.4 | RRF BM25 权重 |
| `hybrid_rrf_k` | 60 | RRF 常数 |
| `retrieval_similarity_threshold` | 0.0 | 检索过滤阈值 (0=禁用) |
| `reranker_method` | `embedding` | 重排序策略 |
| `milvus_collection` | `agentic_rag` | Chunk 向量集合名 |
| `lightrag_entity_collection` | `lightrag_entities` | 实体向量集合名 |
| `lightrag_relation_collection` | `lightrag_relations` | 关系向量集合名 |
| `lightrag_entity_top_k` | 10 | 实体索引 Top K |
| `lightrag_relation_top_k` | 10 | 关系索引 Top K |
| `lightrag_graph_hops` | 2 | 图谱扩展跳数 |
| `lightrag_retrieval_mode` | `hybrid` | LightRAG 检索模式 |
| `agent_max_iterations` | 5 | 验证循环最大迭代 |
| `agent_temperature` | 0.1 | LLM 默认温度 |
| `bge_m3_batch_size` | 32 | Embedding 批处理大小 |

---

## 部署架构

```
┌─────────────────────────────────────────────────────────┐
│                       服务器                             │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ FastAPI       │  │ React 前端    │                    │
│  │ :8000         │  │ :3000        │                    │
│  └──────┬────────┘  └──────────────┘                    │
│         │                                                │
│  ┌──────┴───────────────────────────────┐               │
│  │            外部服务                    │               │
│  │  ┌───────┐ ┌───────┐ ┌───────────┐   │               │
│  │  │ Milvus│ │ Neo4j │ │ DeepSeek  │   │               │
│  │  │:19530 │ │:7687  │ │ API       │   │               │
│  │  └───────┘ └───────┘ └───────────┘   │               │
│  │  ┌───────────┐                       │               │
│  │  │SiliconFlow│                       │               │
│  │  │API (BGE)  │                       │               │
│  │  └───────────┘                       │               │
│  └──────────────────────────────────────┘               │
│  ┌──────────────────────────────────────┐               │
│  │          本地资源 (可选)              │               │
│  │  PaddleOCR-VL (文档 OCR)            │               │
│  │  BGE-M3 本地推理 (备选)             │               │
│  │  MinerU PDF 解析                     │               │
│  └──────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

| 服务 | 端口 | 用途 |
|------|------|------|
| Milvus Standalone | 19530 | 向量检索 (Chunk + Entity + Relation) |
| Neo4j | 7687 (bolt) | 知识图谱存储 + 路径扩展 |
| DeepSeek API | remote | LLM 推理 (分类/生成/验证/抽取) |
| SiliconFlow API | remote | BGE-M3 Embedding + BGE Reranker |

---

## 已完成的性能优化

| 优化项 | 位置 | 效果 |
|--------|------|------|
| Neo4j UNWIND 批量插入 | `neo4j_manager.py:66-102` | ~50x 加速（2 次网络往返替代 N+M 次） |
| BM25 增量追加 | `bm25_retriever.py:36-44` | ~5-10x 加速（O(1) dedup，仅 tokenize 新 chunk） |
| Dense/BM25 查询分离 | `hybrid_retriever.py:31-57` | 语义检索不受实体词干扰 |
| Embedding 并发批处理 | `bge_m3.py:54-70` | ~3-5x 加速（ThreadPoolExecutor, concurrency=8） |
| 图谱关系白名单 | `settings.py:63-69`, `workflow.py:251-291` | 减少低权重关系噪声，降低 LLM token 消耗 |
| Chunk 去重安全化 | `context_merger.py:41` | `hash(text[:500])` 替代 `text[:100]` |
| Validator 结构化失败原因 | `prompts.py:97-114`, `answer_validator.py`, `workflow.py:398-442` | 按原因定向重试，不盲目烧 token |
| Query Router 兜底 | `prompts.py:16-20`, `query_router.py`, `workflow.py:41-54` | `graph_eligible` 信号防止误分类 |
| Graph Agent 子问题生成 | `graph_agent.py:70-101` | 多 query 检索替代简单实体拼接 |
| RRF 权重优化 | `settings.py:56-58` | dense 0.5→0.6, BM25 0.2→0.4 |
| Neo4j `type(r)` bugfix | `neo4j_manager.py:113,143` | `r.type` property 替代 `type(r)` 函数 |

### 待优化瓶颈

- 实体抽取: 每个文档 N 次串行 LLM 调用（可并行化，~10-20x 潜力）
- Embedding 批次: 串行 HTTP 调用（可并发，~3-5x 潜力）
- `chunk_size=512` 放大下游成本（更大 chunk = 更少 LLM/embedding 调用）

---

## 目录结构

```
agentic-rag/
├── config/
│   ├── settings.py              # pydantic-settings (99 行), 加载 .env
│   └── prompts.py               # 全部 LLM prompt (136 行)
├── src/
│   ├── document_parser/         # 文档解析
│   │   ├── mineru_parser.py     # MinerU CLI PDF/Office 解析
│   │   ├── ocr_parser.py        # PaddleOCR-VL 扫描件 OCR
│   │   ├── table_parser.py      # 表格解析 + 跨页合并
│   │   ├── chart_parser.py      # 图表 VLM 描述生成
│   │   └── langchain_compat.py  # PaddleOCR 兼容补丁 (必须先加载)
│   ├── chunker/                 # Chunk 切分
│   │   ├── hierarchical_chunker.py  # 层级切分 (chunk_size=512)
│   │   ├── table_chunker.py         # 表格拆分
│   │   └── context_merger.py        # 合并去重
│   ├── embeddings/
│   │   └── bge_m3.py            # BGE-M3 (API + 本地 GPU 双路)
│   ├── retrieval/               # 检索系统
│   │   ├── vector_retriever.py  # Milvus chunk 向量检索
│   │   ├── bm25_retriever.py    # BM25 关键词检索
│   │   ├── hybrid_retriever.py  # RRF 混合检索 (dense + BM25)
│   │   ├── reranker.py          # 三策略重排序
│   │   ├── graph_expander.py    # Neo4j 图谱路径扩展
│   │   ├── entity_index.py      # LightRAG 实体向量索引
│   │   ├── relation_index.py    # LightRAG 关系向量索引
│   │   └── lightrag_retriever.py # LightRAG 编排器
│   ├── knowledge_graph/         # 知识图谱
│   │   ├── entity_extractor.py  # LLM 实体关系抽取
│   │   ├── neo4j_manager.py     # Neo4j CRUD + UNWIND 批量导入
│   │   ├── graph_query.py       # Text-to-Cypher + 图谱查询
│   │   ├── graphrag_indexer.py  # MS GraphRAG 索引
│   │   └── graphrag_query.py    # MS GraphRAG 查询 (3 种模式)
│   ├── llm/
│   │   └── deepseek.py          # ChatOpenAI 封装
│   ├── agents/                  # Agent 框架
│   │   ├── query_router.py      # 意图分类 + graph_eligible
│   │   ├── retrieval_agent.py   # 检索编排 + 去重
│   │   ├── graph_agent.py       # NER + 图谱扩展 + 子问题生成
│   │   ├── answer_validator.py  # 幻觉检测 + 结构化失败原因
│   │   ├── workflow.py          # LangGraph StateGraph (8 节点, 5 条件边)
│   │   └── tools.py             # LangChain @tool (备选路径)
│   ├── storage/
│   │   ├── doc_store.py         # SQLite 文档元数据 (339 行)
│   │   ├── auto_tagger.py       # LLM 自动标签
│   │   └── config_overrides.py  # 运行时配置覆盖
│   └── evaluation/
│       ├── dataset.py           # 105 条 QA 样本管理
│       ├── runner.py            # 评测执行
│       └── metrics.py           # 指标计算
├── api/
│   ├── main.py                  # FastAPI app (lifespan BM25 rebuild)
│   └── routes/
│       ├── documents.py         # 文档 CRUD + 文件夹管理 (412 行)
│       ├── qa.py                # 问答 /ask + /stream (153 行)
│       ├── management.py        # 系统配置/统计/图谱可视化 (478 行)
│       └── evaluation.py        # 评测接口 (375 行)
├── scripts/
│   ├── ingest_documents.py      # 文档导入 CLI
│   ├── build_graph.py           # 构建 Neo4j 知识图谱
│   ├── build_graphrag.py        # 构建 MS GraphRAG 索引
│   ├── build_lightrag_index.py  # 构建 LightRAG 实体+关系向量索引
│   ├── run_evaluation.py        # 运行评测
│   ├── diagnose.py              # 系统诊断
│   └── setup_milvus.sh          # Milvus 容器部署脚本
├── tests/                       # 测试
├── frontend/                    # React 前端
│   └── src/
│       ├── App.tsx              # 主应用
│       ├── components/          # 组件
│       ├── pages/               # 页面
│       ├── hooks/               # 自定义 hooks
│       ├── lib/                 # 工具库
│       └── contexts/            # React contexts
├── data/
│   ├── raw/                     # 原始文档
│   ├── processed/               # MinerU 处理输出
│   ├── documents.db             # SQLite 文档元数据
│   ├── bm25_index/              # BM25 持久化索引
│   └── graphrag/                # MS GraphRAG 数据
└── pyproject.toml               # uv 项目配置
```

---

## 外部服务依赖

| 服务 | 端口 | 必需 | 用途 |
|------|------|------|------|
| Milvus Standalone | 19530 | 是 | Chunk + Entity + Relation 向量检索 |
| Neo4j | 7687 (bolt) | 是 | 知识图谱存储 + 路径扩展 |
| DeepSeek API | remote | 是 | 所有 LLM 调用 (chat + reasoning) |
| SiliconFlow API | remote | 是 | BGE-M3 Embedding + BGE Reranker (default) |

---

## 启动命令

```bash
# 后端
uv run -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend && npm run dev

# TypeCheck 前端
cd frontend && npx tsc --noEmit

# 文档导入
uv run python scripts/ingest_documents.py <file>

# 构建知识图谱
uv run python scripts/build_graph.py

# 构建 LightRAG 索引 (需先有 Neo4j 数据)
uv run python scripts/build_lightrag_index.py

# 安全测试 (无需外部服务)
uv run -m pytest tests/test_parser.py tests/test_chunker.py tests/test_graph.py -v

# 全量测试 (需 Milvus/Neo4j/models 运行)
uv run -m pytest tests/ -v

# 系统诊断
uv run python scripts/diagnose.py
```
