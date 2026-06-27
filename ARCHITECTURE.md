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
│  GET  /api/v1/system/*            GET  /api/v1/evaluation/*          │
│  POST /api/v1/excel/*   (Excel QA 独立端点, 直接走 ExcelQA.retrieve) │
│  POST /api/v1/auth/*    (登录/注册/用户管理, auth_enabled 控制开关) │
│  GET  /health                                                         │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │   Agent Workflow       │
                │  (LangGraph StateGraph) │
                └───────────┬───────────┘
                            │
                            ▼
                     query_router
               (LLM 语义意图分类,
                不决定 SQL 路由)
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
     chitchat         retrieval_agent     lightrag_agent
     → END            (统一召回:            (entity→relation→
                       doc chunks +         graph→chunk)
                       table schemas +         │
                       sheet summaries         │ fallback:
                       同库)                   │ graph_agent→
                         │                     │ retrieval_agent
                         │                 ┌───┘
                         └─────────────────┘
                                   │
                                   ▼
                  _route_after_retrieval  (★ NEW 短路)
                  ┌──────────────┴───────────────┐
                  ▼                              ▼
        召回全为数据表 + 含 excel_sheet       其他情况 (空/混合/非数据表)
        → sql_agent (跳过 LLM 判断)         → answer_generator
                  │                              │
                  │                              ▼
                  │              answer_generator (生成 + 自检合并, 单次 LLM)
                  │                              │
                  │                              ▼
                  │              _route_after_generation (统一决策点)
                  │                              │
                  │              ┌────────────────┼────────────────┐
                  │              ▼                ▼                ▼
                  │          召回充分        信息不足         rerouted_to_sql=True
                  │          answer 正常     + 有 excel_sheet   (sql_agent 已执行)
                  │          → END          chunk + 未重判      → END (直接结束)
                  │                          + iter < max
                  │                              │
                  └──────────────────────────────┘
                                   │
                                   ▼
                              sql_agent
                        (条件触发 SQL Tool Call)
                        NL2SQL → 执行 → SQL 结果
                                   │
                                   │ rerouted_to_sql=True
                                   ▼
                        answer_generator
                    (基于 SQL 结果生成最终答案)
                                   │
                                   ▼
                       _route_after_generation
                                   │
                          rerouted_to_sql=True
                          → END (直接结束)
                                   │
                                   ▼
                       Final Answer + Citations
```

---

## LangGraph 工作流详情

### AgentState（24 字段）

```python
query: str              # 原始用户问题
query_type: str         # chitchat | simple_fact | multi_hop | comparison | definition
                        # [UNIFIED] sql_query 已移除：所有非 chitchat 查询统一走向量召回
confidence: float       # 分类置信度 0.0-1.0
graph_eligible: bool    # 多实体+关系词 → 允许图谱增强

documents: list[dict]   # 检索到的 chunks (Annotated[list, operator.add])
                        # 统一召回：文档块 + 表结构 + 表摘要都在同一向量库
graph_context: str      # 图谱扩展后的格式化文本
graph_entities: list[str]   # 相关实体名
sub_queries: list[str]      # LightRAG/graph_agent 生成的检索子问题
graphrag_context: str       # MS GraphRAG 结果 (unreachable)

retrieval_path: str     # 检索路径说明（可观测性）
retrieval_debug: dict   # 检索调试信息（SQL 查询、结果等）
search_debug_data: dict # 前端检索调试面板数据
draft_answer: str       # 答案草稿
final_answer: str       # 最终答案
citations: list[str]    # 引用 doc_id_chunk_id 列表
validation: dict        # [MERGED] validation 节点已合并到 answer_generator
validation_feedback: str    # [DEPRECATED] 结构化失败反馈（保留兼容）

iteration: int          # 当前迭代
max_iterations: int     # 最大迭代 (默认 5)
error: str              # 错误信息
folder: str             # 文件夹过滤
tags: list[str]         # 标签过滤
doc_ids: list[str]      # 单文件筛选（前端选中具体文件时传入）

# [UNIFIED] SQL 作为条件性 Tool Call 的防死循环标志
rerouted_to_sql: bool   # sql_agent 被触发后置 True；
                        # 触发路径有两条：
                        #   (1) 数据表短路: _route_after_retrieval 检测召回全为数据表 → sql_agent
                        #   (2) 条件 Tool Call: _route_after_generation 检测 answer 信息不足 + excel_sheet chunk → sql_agent
                        # 下一轮 _route_after_generation 检测到 True + 仍信息不足 → END (防死循环)
```

### 节点 (8 个)

| 节点 | 职责 |
|------|------|
| `query_router` | LLM 语义意图分类：query_type + confidence + graph_eligible（仅语义意图，不决定 SQL） |
| `chitchat` | 直接 LLM 回答，无检索，立即终止 |
| `sql_agent` | **[条件触发 Tool Call]** NL2SQL：向量召回 Sheet → 多表选择 → NL2SQL → 执行（含重试）；仅由 `_route_after_generation` 在召回含 excel_sheet chunk + answer 信息不足时触发 |
| `retrieval_agent` | **[统一召回]** Hybrid (dense + BM25) → RRF fusion → rerank → dedup（文档块 + 表结构 + 表摘要同库） |
| `graph_agent` | LLM NER → Neo4j expand → 子问题生成 → 实体富化 BM25 → retrieval_agent |
| `lightrag_agent` | Entity Index + Relation Index → Neo4j expand → chunk retrieve（含 fallback） |
| `graphrag_search` | **[UNREACHABLE]** MS GraphRAG global/local/drift search |
| `answer_generator` | **[MERGED]** 单次 LLM 调用同时生成答案 + 自检（原 answer_validator 职责已合并）；含引用生成；`intermediate` 标志延迟显示中间答案 |

> **[MERGED]** `answer_validator` 节点已合并到 `answer_generator`：单次 LLM 调用同时生成 + 自检，重判信号改用正则匹配 `_answer_indicates_insufficient` + `_has_excel_sheet_chunk`，不再依赖独立的 validator LLM 调用。

### 边

| 类型 | 源 → 目标 | 条件 |
|------|-----------|------|
| 固定 | START → query_router | — |
| 固定 | chitchat → END | — |
| 固定 | sql_agent → answer_generator | — |
| 条件 | retrieval_agent → answer_generator / sql_agent | `_route_after_retrieval`（**短路**：召回全为数据表类 + 含 excel_sheet chunk → sql_agent） |
| 条件 | lightrag_agent → answer_generator / sql_agent | `_route_after_retrieval`（同上，避免重复 LLM 判断） |
| 条件 | query_router → chitchat / retrieval_agent / lightrag_agent | `_route_by_query_type`（无 sql_query 分支） |
| 条件 | graph_agent → retrieval_agent | `_route_for_multi_hop`（无条件路由到 retrieval） |
| 条件 | graphrag_search → ... | `_route_after_graphrag` [UNREACHABLE] |
| 条件 | answer_generator → END / sql_agent | `_route_after_generation`（条件触发 SQL Tool Call） |

> **[SHORT-CIRCUIT]** `_route_after_retrieval` 是数据表场景的快速通道：
> 当用户已通过 folder/tags/doc_ids 限定到纯数据表文件（Excel sheet 摘要 / SQL 结果 doc），
> 召回后无需再经过 `answer_generator` 的 LLM 判断 "信息是否不足 → 是否触发 SQL"，
> 直接进入 `sql_agent` 执行 NL2SQL，节省一次 LLM 往返。
> 判断函数：`_is_data_table_document()`（基于 `metadata.source` / `source_type` / `chunk_id` 前缀）+
> `_all_documents_are_data_tables()` + `_has_excel_sheet_chunk()` 双重校验。
> 混合场景（含非数据表文档）保持原流程，由 `_route_after_generation` 兜底触发 SQL。

### 统一召回流程（`_route_by_query_type` + `_route_after_generation`）

**设计文档三点决策**：统一检索 → LLM 决策 → 必要时调用 SQL 工具 → 生成最终答案。

```
┌────────────────────────────────────────────────────────────────────────┐
│ workflow.invoke(query, folder, tags, doc_ids)                          │
│   [UNIFIED] 不再计算 force_sql：所有 query 统一走向量召回                │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
                            query_router (仅语义意图分类)
                                   │
       ┌───────────┬───────────────┼─────────────┬──────────────┐
       ▼           ▼               ▼             ▼              ▼
   chitchat   retrieval_agent  lightrag_agent  (其他)        (其他)
   → END         │                │             │             │
                 │                │             ▼             ▼
                 │                │     graph_agent    retrieval_agent
                 │                │             │
                 │                │             ▼
                 │                │      retrieval_agent
                 │                │             │
                 └────────────────┴─────────────┘
                                   ▼
                          answer_generator (统一生成 + 自检)
                                   │
                                   ▼
                       _route_after_generation (统一决策点)
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
        rerouted_to_sql=True   召回充分              信息不足
        → 直接 END             answer 正常           + 有 excel_sheet
        (sql_agent 已执行,     → END                 chunk + 未重判
         不再路由)             (设计文档第1点)       + iter < max
                                                      │
                                                      ▼
                                                 sql_agent
                                                 (条件性 Tool Call)
                                                      │
                                                      │ 设置 rerouted_to_sql=True
                                                      ▼
                                          answer_generator (生成最终答案)
                                                      │
                                                      ▼
                                          _route_after_generation
                                                      │
                                             rerouted_to_sql=True
                                             → 直接 END
                                             (不再路由, 流程结束)
                                                      │
                                                      ▼
                                          Final Answer + Citations
```

详细分支：

```
query_router (仅语义意图分类，不决定 SQL)
  │
  ├─ chitchat ⇒ chitchat → END
  │
  ├─ holistic ⇒ retrieval_agent → answer_generator → _route_after_generation → END/(sql_agent)
  │   (MS GraphRAG 已停用，改为走普通检索)
  │
  ├─ multi_hop / comparison / (simple_fact|definition + graph_eligible=True)
  │   ⇒ lightrag_agent → answer_generator → _route_after_generation → END/(sql_agent)
  │   │
  │   └─ lightrag_agent 内部:
  │      ├─ LightRAG entity index 有数据 → Entity Index → Relation Index → Graph Expand → Chunk Retrieve
  │      └─ entity index 为空 (.count() == 0) → fallback: graph_agent → retrieval_agent
  │
  └─ simple_fact / definition (graph_eligible=False)
      ⇒ retrieval_agent → answer_generator → _route_after_generation → END/(sql_agent)
```

**关键变更（统一召回 + 条件触发 SQL）**：
- `multi_hop` / `comparison` 的主路径是 `lightrag_agent`（而非 `graph_agent`）。`lightrag_agent` 在 LightRAG 索引为空时自动 fallback 到 `graph_agent → retrieval_agent` 路径，保证可用性。
- **[UNIFIED]** `sql_query` 路由分支已移除：所有非 chitchat 查询统一走向量召回（retrieval_agent / lightrag_agent），SQL 作为召回后 answer_generator 的条件性 Tool Call 触发（见 `_route_after_generation`）。用户选 Excel 文件不再特殊路由，而是自然进入统一召回（Excel sheet 摘要已作为 chunk 存入主向量库，metadata.source="excel_sheet"）。
- **[UNIFIED]** `force_sql` 状态字段与 `_should_force_sql` 函数已移除：不再基于 folder/tags/doc_ids 全为 Excel 文件时强制走 sql_query 路由。

### 条件触发 SQL Tool Call（`_route_after_generation`）

```
answer_generator (统一生成 + 自检)
  │
  ├─ rerouted_to_sql=True → 直接 END
  │   [SHORT-CIRCUIT] sql_agent 已作为 Tool Call 执行过，answer_generator 已基于
  │   SQL 结果生成最终答案。无论 answer 是否信息不足，都不再路由——
  │   - answer 正常 → 最终答案，END
  │   - answer 仍信息不足 → 已穷尽统一召回 + NL2SQL 两条路径，END 避免死循环
  │
  ├─ 未重判 + 召回含 excel_sheet chunk + answer 信息不足 + iteration < max_iter
  │   → sql_agent (条件性 Tool Call：召回中含相关数据表，LLM 判断 SQL 可能获得答案)
  │   └─ sql_agent 返回时设置 rerouted_to_sql=True，下一轮直接 END
  │
  └─ 其他 → END
      (召回充分 → answer 正常 / 召回不充分但无数据表可尝试 SQL → 返回"无法回答")
```

**条件触发 SQL Tool Call 的规则**（对应设计文档三点决策）：
1. **召回充分**：answer_generator 基于统一召回的上下文（文档块 + 表结构 + 表摘要）生成回答，answer 正常 → 直接 END（设计文档第 1 点）
2. **召回不充分 + 有数据表**：answer 含"信息不足"短语 + 召回含 excel_sheet chunk + 未重判过 + iteration < max → sql_agent 触发 NL2SQL Tool Call，SQL 结果与上下文一起交给 answer_generator 生成最终答案（设计文档第 2 点）
3. **召回不充分 + 无数据表**：answer 信息不足但召回中无 excel_sheet chunk → END，返回"无法回答"（设计文档第 3 点）

**SQL Tool Call 触发条件**：
1. `rerouted_to_sql=False`（尚未触发过 SQL Tool Call，由 short-circuit 保证防死循环）
2. 回答文本含"信息不足"短语（`_answer_indicates_insufficient` 正则匹配）
3. 检索 documents 中存在 `metadata.source == "excel_sheet"` 的 chunk（统一召回检到了 sheet 摘要 chunk）
4. `iteration < max_iterations`（answer_generator 已 +1 后的值）

SQL Tool Call 后 sql_agent 返回的 SQL 执行结果与之前的 sheet 摘要 chunk **累加**（LangGraph `operator.add`），answer_generator 看到"sheet 摘要 + 真实 SQL 结果"双重信息生成更准确的回答。

**★ 死循环防护**（`rerouted_to_sql=True` 短路）：
- sql_agent 被触发即置 `rerouted_to_sql=True`，下一轮 `_route_after_generation` 检测到 `rerouted_to_sql=True` → **直接 END**，不再检查 answer 是否信息不足，不再二次触发 sql_agent。
- **理由**：sql_agent 是条件性 Tool Call（非独立路由），执行后 answer_generator 已基于 SQL 结果生成最终答案。无论结果如何，流程结束——answer 正常是最终答案，answer 信息不足说明已穷尽统一召回 + NL2SQL 两条路径，继续烧 token 无意义。

**⚠️ iteration 边界对齐**（`will_reroute` ↔ `_route_after_generation`）：
- answer_generator 输入 `iteration=N`，输出 `iteration=N+1`
- `_route_after_generation` 读取 `iteration=N+1`，检查 `N+1 < max_iter`
- answer_generator 的 `will_reroute`（控制 `intermediate` 标志）必须用 `N+1 < max_iter` 才能与之对齐
- **Bugfix**：之前 answer_generator 用 `N < max_iter`，当 `N=max_iter-1` 时 `will_reroute=True`（前端不渲染中间答案）但 `_route_after_generation` 判 END → 前端卡死等待永远不来的最终答案

### sql_agent 失败处理（统一不再 fallback）

`_node_sql_agent` 现在仅作为条件性 Tool Call 触发，**不再 fallback 到 retrieval_agent**（统一召回已在前序步骤完成，二次 fallback 没有意义，反而可能造成死循环）：

| retrieval_path | 含义 | 失败处理 |
|----------------|------|---------|
| `sql_nl2sql` | NL2SQL 成功 | 输出 SQL 结果文档（含 sheet 摘要 + SQL 结果） |
| `sql_no_sheet` | 无 sheet 召回 | 返回空 documents，answer_generator 生成"无法回答" |
| `sql_error` | NL2SQL 异常 | 返回空 documents，answer_generator 生成"无法回答" |

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

### 10. Excel RAG 子系统 (`src/excel_rag/`)

独立结构化数据查询子系统，处理 `.xlsx` 文件。当 `settings.excel_rag_enabled=True` 时，
文档入库流程会自动调用 `src/excel_rag/pipeline.ingest_excel()`，将 Excel 拆分为
"元数据层 + 数据层"双轨存储，并写入 Milvus 独立集合 `excel_sheets`，与主 chunk 集合并存。

| 文件 | 类 | 职责 | 技术细节 |
|------|-----|------|---------|
| `parser.py` | `ExcelParser` | Sheet/Column 解析 | 输出 `SheetInfo` + `ColumnInfo`；前 N 行采样做类型推断 (`excel_sample_rows_for_inference=200`) |
| `summarizer.py` | `SheetSummarizer` | Sheet 摘要 + 列名映射 | LLM 生成自然语言摘要 + 字段映射 (display_name ↔ column_name) |
| `store.py` | `ExcelStore` | 元数据 + 动态数据表 | SQLite 表 `excel_sheets` (元数据) + `excel_data_<doc_id>_<sheet_idx>` (每 sheet 一张动态表) |
| `vector_store.py` | `ExcelVectorStore` | 摘要向量检索 | Milvus 独立集合 `excel_sheets` (IVF_FLAT, COSINE, nlist=128, dim=1024) |
| `nl2sql.py` | `NL2SQL` + `ExcelQAExecutor` | NL2SQL + 执行 | `execute_with_retry()` 自动修正 (max_retries=2, timeout=5s)；`format_answer()` 双模式 (表格 + 自然语言) |
| `qa.py` | `ExcelQA` | 查询编排 | `retrieve()` → 多表选择 → NL2SQL → 执行；与主 workflow 的 `sql_agent` 节点共享 NL2SQL 实现 |
| `pipeline.py` | — | 入库编排 | `ingest_excel()` 串接 parse → summarize → store → vector_store；同时把 sheet_summary 作为 chunk 注入主 collection，供混合召回 |

**字段映射三属性**（`ColumnInfo`，解决 SQL 字段名与显示名不一致问题）：

| 属性 | 含义 | 示例 |
|------|------|------|
| `display_name` | 用户可见字段名（中英文混合，描述性） | `"销售金额"` / `"Revenue (¥)"` |
| `column_name` | 数据库实际列名（snake_case，SQL 安全） | `"sales_amount"` / `"revenue_cny"` |
| `data_type` | 列类型 | `INTEGER` / `REAL` / `TEXT` |

兼容旧数据：`store._normalize_columns()` 自动把旧 `cn` / `en` / `type` 字段转换为三属性格式。

### 11. 鉴权系统 (`src/auth.py`)

| 组件 | 说明 |
|------|------|
| `auth_enabled` (settings) | 全局开关。`False` 时所有 API 端点匿名可访问，跳过 `current_user` 依赖 |
| 用户表 (`users` SQLite 表) | 字段: id / username / role / pass_hash / created_at / is_active |
| 角色 | `admin`（全部权限）/ `user`（限上传配额）/ `guest`（限聊天长度） |
| `auth_allow_register` | 默认 `False`，仅管理员可创建账号 |
| `auth_guest_chat_max_length` | 访客单次聊天输入字符上限 |
| `auth_user_upload_daily_limit` | 普通用户每日上传文件数上限 |
| 密码哈希 | PBKDF2-HMAC-SHA256 |
| 依赖注入 | `get_current_user` / `get_current_user_optional` / `require_admin` |
| `RequestIdMiddleware` | 全局注入 `X-Request-ID`，串联日志 + LLM token 统计 |

### 12. 缓存层 (`src/cache/`)

统一缓存抽象，LLM 响应 / Embedding / Reranker 共用同一后端，按 `namespace` 区分 key 前缀。
启用缓存可避免对相同输入重复调用 DeepSeek/SiliconFlow 远程 API。

| 文件 | 职责 |
|------|------|
| `base.py` | `CacheBackend` 抽象基类：`get` / `set` / `delete` / `clear_namespace` |
| `factory.py` | `get_cache()` 工厂；`_BACKEND_BUILDERS` 注册表，按 `settings.cache_backend` 选择后端 |
| `memory_backend.py` | 进程内 LRU（默认；最快，重启丢失，单进程适用） |
| `sqlite_backend.py` | SQLite 持久化（`data/cache.db`，多 worker 共享） |
| `garnet_backend.py` / `redis_backend.py` | Garnet/Redis 协议相同，跨进程共享 + 原生 TTL（生产推荐） |
| `noop_backend.py` | 禁用缓存占位（`cache_backend="none"` 或 `"noop"`） |
| `llm/cached_wrapper.py` | LangChain `BaseChatModel` 包装器，透明拦截 `invoke` / `generate` 落缓存 |

namespace 前缀：`llm` (LLM 响应)、`emb` (embedding 向量)、`rerank` (reranker 结果)。
全局开关 `cache_enabled=False` 时所有命名空间禁用，走真实请求。

### 13. LLM Token 统计 (`src/llm/token_stats.py`)

按 `X-Request-ID` 收集 DeepSeek 调用的 prompt/completion/total_tokens，
通过 `/api/v1/admin/llm-stats/*` 接口暴露给管理员面板，便于成本观测。

### 14. 评测 (`src/evaluation/`)

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
                      └─ → _route_after_retrieval → answer_generator
                          (数据表短路: → sql_agent → answer_generator)

  ┌─ 数据表短路（_route_after_retrieval）─────────────────────────────────┐
  │ 召回全为数据表类 (Excel sheet 摘要 / SQL 结果 doc) + 含 excel_sheet: │
  │   retrieval_agent / lightrag_agent → sql_agent → answer_generator    │
  │   （跳过 answer_generator 的首次 LLM 判断）                            │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## API 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/documents/upload` | 上传文档，触发全流程处理（Excel 自动分流到 `excel_rag.pipeline`） |
| `GET` | `/api/v1/documents/list` | 文档列表 (folder/tags/status 过滤) |
| `GET` | `/api/v1/documents/{id}/status` | 查询处理状态 |
| `GET` | `/api/v1/documents/{id}/chunks` | 获取文档 Chunks |
| `GET` | `/api/v1/documents/{id}/content` | 获取文档 Markdown 内容 |
| `DELETE` | `/api/v1/documents/{id}` | 级联删除 (Milvus + BM25 + Neo4j + SQLite + excel_data_* 动态表) |
| `PUT` | `/api/v1/documents/{id}/move` | 移动文档到文件夹 |
| `POST` | `/api/v1/documents/{id}/tags` | 设置标签 |
| `POST` | `/api/v1/documents/{id}/retry` | 重新处理失败文档 |
| `GET/POST/DELETE` | `/api/v1/documents/folders/*` | 文件夹管理 |
| `POST` | `/api/v1/qa/ask` | 问答 (非流式) |
| `POST` | `/api/v1/qa/stream` | 问答 (SSE 流式, 带节点标签 + 调试面板数据) |
| `POST` | `/api/v1/excel/qa` | Excel 独立问答 (直接 `ExcelQA.retrieve`, 不走 LangGraph) |
| `GET` | `/api/v1/system/config` | 系统配置查看 |
| `GET` | `/api/v1/system/connectivity-check` | 外部服务连通性检查 |
| `GET` | `/api/v1/system/stats` | 系统统计 |
| `POST` | `/api/v1/system/cleanup-orphans` | 清理孤儿数据 |
| `GET` | `/api/v1/system/graph/overview` | 图谱可视化数据 |
| `GET` | `/api/v1/system/graph/entity/{name}` | 实体详情 |
| `GET/PUT/DELETE` | `/api/v1/system/config/editable/*` | 运行时配置覆盖 |
| `*` | `/api/v1/admin/cache/*` | 缓存管理 (统计/清理/重载, 管理员) |
| `*` | `/api/v1/admin/llm-stats/*` | LLM token 统计查询 (管理员) |
| `*` | `/api/v1/admin/search-debug/*` | 检索调试面板数据 (管理员) |
| `*` | `/api/v1/admin/system/*` | 系统管理 (管理员) |
| `*` | `/api/v1/admin/graph/*` | 图谱管理 (管理员) |
| `POST` | `/api/v1/auth/login` | 登录 (返回 JWT) |
| `POST` | `/api/v1/auth/register` | 注册 (`auth_allow_register=True` 时启用) |
| `GET` | `/api/v1/auth/me` | 当前用户信息 |
| `*` | `/api/v1/auth/users/*` | 用户管理 (管理员) |
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
| `reranker_method` | `embedding` | 重排序策略 (cosine / cross-encoder / hybrid) |
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
| `excel_rag_enabled` | `True` | Excel RAG 子系统开关 |
| `excel_milvus_collection` | `excel_sheets` | Excel sheet 摘要向量集合名 |
| `excel_sql_timeout_ms` | 5000 | Excel NL2SQL 执行超时 |
| `excel_sql_max_retries` | 2 | Excel NL2SQL 自动修正重试次数 |
| `excel_sample_rows_for_inference` | 200 | 列类型推断采样行数 |
| `cache_enabled` | `True` | 全局缓存开关 (LLM/embedding/rerank) |
| `cache_backend` | `memory` | 缓存后端 (memory/sqlite/garnet/redis/none) |
| `cache_ttl_seconds` | 86400 | 默认缓存 TTL |
| `cache_db_path` | `data/cache.db` | sqlite 后端数据库路径 |
| `cache_llm_namespace` | `llm` | LLM 响应缓存 key 前缀 |
| `cache_embedding_namespace` | `emb` | embedding 缓存 key 前缀 |
| `garnet_url` | `redis://127.0.0.1:16389/0` | Garnet/Redis 服务器地址 |
| `auth_enabled` | `True` | 鉴权开关 |
| `auth_allow_register` | `False` | 自助注册开关 |
| `auth_guest_chat_max_length` | 500 | 访客聊天输入上限 |
| `auth_user_upload_daily_limit` | 20 | 普通用户每日上传上限 |

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
| answer_generator 单次 LLM 合并生成+自检 | `workflow.py:_node_answer_generator` | 比独立 validator 节省 1 次 LLM 往返/轮；重判改用正则 `_answer_indicates_insufficient` |
| 数据表短路 `_route_after_retrieval` | `workflow.py` | 纯数据表场景跳过 answer_generator 首次 LLM 判断，节省 1 次往返 |
| Query Router 兜底 | `prompts.py:16-20`, `query_router.py`, `workflow.py:41-54` | `graph_eligible` 信号防止误分类 |
| Graph Agent 子问题生成 | `graph_agent.py:70-101` | 多 query 检索替代简单实体拼接 |
| RRF 权重优化 | `settings.py:56-58` | dense 0.5→0.6, BM25 0.2→0.4 |
| Neo4j `type(r)` bugfix | `neo4j_manager.py:113,143` | `r.type` property 替代 `type(r)` 函数 |
| 统一缓存层 (`src/cache/`) | `cache/factory.py` + `llm/cached_wrapper.py` | LLM/embedding/rerank 同输入零成本命中，避免重复远程调用 |
| Chunk GC (`src/storage/gc.py`) | `storage/gc.py` | ref_count=0 的 ChunkContent 在 `chunk_gc_ttl_days` 后物理删除 + Milvus 向量清理 |

### 待优化瓶颈

- 实体抽取: 每个文档 N 次串行 LLM 调用（可并行化，~10-20x 潜力）
- Embedding 批次: 串行 HTTP 调用（可并发，~3-5x 潜力）
- `chunk_size=512` 放大下游成本（更大 chunk = 更少 LLM/embedding 调用）

---

## 目录结构

```
BaizeMind/
├── config/
│   ├── settings.py              # pydantic-settings, 加载 .env (含 Excel/Cache/Auth 配置)
│   └── prompts.py               # 全部 LLM prompt
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
│   │   ├── reranker.py          # 三策略重排序 (cosine / cross-encoder / hybrid)
│   │   ├── graph_expander.py    # Neo4j 图谱路径扩展
│   │   ├── entity_index.py      # LightRAG 实体向量索引
│   │   ├── relation_index.py    # LightRAG 关系向量索引
│   │   ├── lightrag_retriever.py # LightRAG 编排器
│   │   └── debug_formatter.py   # 检索调试面板数据格式化
│   ├── knowledge_graph/         # 知识图谱 (证据驱动)
│   │   ├── entity_extractor.py  # LLM 实体关系抽取
│   │   ├── neo4j_manager.py     # Neo4j CRUD + UNWIND 批量导入
│   │   ├── graph_query.py       # Text-to-Cypher + 图谱查询
│   │   ├── graphrag_indexer.py  # MS GraphRAG 索引
│   │   ├── graphrag_query.py    # MS GraphRAG 查询 (3 种模式)
│   │   ├── evidence.py          # 证据模型 (ENTITY/ENTITY_ATTRIBUTE/FACT/FACT_ATTRIBUTE)
│   │   ├── evidence_writer.py  # 证据写入 (含去重 + active flag)
│   │   ├── chunk_manager.py     # ChunkContent 去重 + 引用计数
│   │   ├── graph_sync_worker.py # GraphSyncTask 队列 → Neo4j 批量同步
│   │   └── attribute_resolver.py # 实体属性解析
│   ├── excel_rag/               # ★ Excel RAG 子系统
│   │   ├── parser.py            # ExcelParser → SheetInfo / ColumnInfo (三属性)
│   │   ├── summarizer.py        # LLM 摘要 + 字段映射
│   │   ├── store.py             # excel_sheets 元数据 + excel_data_<doc>_<sheet> 动态表
│   │   ├── vector_store.py     # Milvus excel_sheets 独立集合
│   │   ├── nl2sql.py             # NL2SQL + execute_with_retry + format_answer
│   │   ├── qa.py                # ExcelQA 查询编排
│   │   └── pipeline.py          # ingest_excel / delete_excel 入库编排
│   ├── cache/                   # ★ 统一缓存层
│   │   ├── base.py              # CacheBackend 抽象
│   │   ├── factory.py           # get_cache() 工厂 + _BACKEND_BUILDERS 注册
│   │   ├── memory_backend.py    # 进程内 LRU (默认)
│   │   ├── sqlite_backend.py    # SQLite 持久化
│   │   ├── garnet_backend.py    # Garnet (Redis 协议)
│   │   ├── redis_backend.py     # Redis
│   │   └── noop_backend.py      # 禁用缓存占位
│   ├── llm/
│   │   ├── deepseek.py          # ChatOpenAI 封装 (get_chat_llm / get_reasoner_llm)
│   │   ├── cached_wrapper.py    # ★ 缓存透明包装器 (拦截 invoke/generate)
│   │   └── token_stats.py       # ★ LLM token 统计 (按 X-Request-ID 聚合)
│   ├── storage/
│   │   ├── doc_store.py         # SQLite 文档元数据 (含 folders/tags/evidence/GraphSyncTask)
│   │   ├── auto_tagger.py       # LLM 自动标签
│   │   ├── config_overrides.py  # 运行时配置覆盖
│   │   └── gc.py                # Chunk GC (ref_count=0 → 物理删除, chunk_gc_ttl_days)
│   ├── auth.py                  # ★ 鉴权 (用户/角色/JWT/PBKDF2)
│   ├── logging_config.py        # 结构化日志 + request_id 上下文
│   ├── agents/                  # Agent 框架
│   │   ├── query_router.py      # 意图分类 + graph_eligible
│   │   ├── retrieval_agent.py   # 检索编排 + 去重
│   │   ├── graph_agent.py       # NER + 图谱扩展 + 子问题生成
│   │   ├── answer_validator.py  # 幻觉检测 (类保留供独立脚本调用, workflow 不再实例化)
│   │   ├── workflow.py          # LangGraph StateGraph (8 节点, 7 条件边)
│   │   └── tools.py             # LangChain @tool (备选路径)
│   └── evaluation/
│       ├── dataset.py           # 105 条 QA 样本管理
│       ├── runner.py            # 评测执行
│       └── metrics.py           # 指标计算
├── api/
│   ├── main.py                  # FastAPI app (RequestIdMiddleware + lifespan BM25 rebuild)
│   └── routes/
│       ├── documents.py         # 文档 CRUD + 文件夹管理 + Excel 自动分流
│       ├── qa.py                # 问答 /ask + /stream (NODE_LABELS 节点标签)
│       ├── management.py        # 系统配置/统计/图谱可视化
│       ├── evaluation.py        # 评测接口
│       ├── excel.py             # ★ Excel 独立问答端点
│       ├── auth.py              # ★ 登录/注册/用户管理
│       └── admin/               # ★ 管理员子目录
│           ├── cache_admin.py   # 缓存管理
│           ├── llm_stats.py     # LLM token 统计
│           ├── search_debug.py  # 检索调试
│           ├── system.py        # 系统管理
│           └── graph_admin.py   # 图谱管理
├── scripts/
│   ├── ingest_documents.py      # 文档导入 CLI (PDF/Office)
│   ├── build_graph.py           # 构建 Neo4j 知识图谱
│   ├── build_graphrag.py        # 构建 MS GraphRAG 索引
│   ├── build_lightrag_index.py  # 构建 LightRAG 实体+关系向量索引
│   ├── migrate_kg_to_evidence.py # 旧 Neo4j KG → 证据驱动模型迁移
│   ├── run_evaluation.py        # 运行评测
│   ├── diagnose.py              # 系统诊断
│   └── setup_milvus.sh          # Milvus 容器部署脚本
├── tests/                       # 测试 (test_parser/chunker/graph/evidence/evidence_pipeline 离线安全)
├── frontend/                    # React 18 + Vite + Tailwind + shadcn/ui
│   └── src/
│       ├── App.tsx              # 主应用 + 路由 (含 /login /users /config 管理员页)
│       ├── components/
│       │   ├── ChatMessage.tsx           # 聊天消息渲染 (含 SqlResultTable)
│       │   ├── SqlResultTable.tsx        # ★ SQL 结果表渲染 (全局 5 行预览)
│       │   └── SearchDebugPanel.tsx      # 检索调试面板 (含 SqlResultTable)
│       ├── pages/               # Documents / Graph / Workflow / Evaluation / Tests
│       ├── hooks/               # useAuth / useDocuments / ...
│       ├── lib/                 # API 客户端 + 工具
│       └── contexts/            # React contexts (auth / theme / ...)
├── data/
│   ├── raw/                     # 原始文档
│   ├── processed/               # MinerU 处理输出
│   ├── documents.db             # SQLite 文档元数据 + ChunkContent + Evidence + GraphSyncTask + users
│   ├── cache.db                 # sqlite 缓存后端 (cache_backend="sqlite" 时)
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
