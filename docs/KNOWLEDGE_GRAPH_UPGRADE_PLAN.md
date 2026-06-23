# 知识图谱增量更新架构升级方案

## 定位

本文档定义 Agentic-GraphRAG 知识图谱模块从当前**直接写入模式**升级为**Evidence 驱动增量更新模式**的完整技术方案。

---

# Part A: 最终目标架构

## A.1 总体架构

```
Milvus：存 ChunkContent + Embedding
SQLite：存 Document / DocChunkRef / Evidence / GraphSyncTask — 作为 Source of Truth
Neo4j：存 Entity / Fact / Attribute — 作为 Materialized View
```

最终一致性链路：

```
Active Documents
    ↓
Active DocChunkRef
    ↓
Active ChunkContent
    ↓
Active Evidence (SQLite)
    ↓
Neo4j Graph
```

核心原则：

```
Neo4j Graph
    =
Aggregation(SQLite Active Evidence)
    =
Aggregation(Active ChunkContent)
    =
Aggregation(Active DocChunkRef)
    =
Aggregation(Active Documents)
```

## A.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **Document 是业务对象** | 版本管理、生命周期、更新/删除入口。不直接参与知识计算。 |
| **Chunk 是增量计算单元** | 最小处理单位。Embedding / Evidence 抽取都以 Chunk 为边界。 |
| **ChunkContent 去重复用** | 相同内容的 Chunk 只存 1 份、只 Embedding 1 次、只抽取 1 次 Evidence。通过 `chunk_hash` 唯一标识。 |
| **Evidence 是 Source of Truth** | SQLite 存储所有原子证据。Neo4j 不得被直接修改，所有状态由 Evidence 推导。 |
| **Neo4j 是物化视图** | 只负责图查询/GraphRAG/路径分析/推理。所有节点和关系可由 Evidence 完全重建。 |
| **最终一致性** | Evidence 落库后，Neo4j 允许延迟同步。通过 GraphSyncTask 队列保证最终一致。 |

## A.3 数据模型全览

```
┌──────────────────────────────────────────────────────────────┐
│                         SQLite                               │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ Document │───→│ DocChunkRef  │←───│ ChunkContent │       │
│  │(元数据)   │    │(引用关系)    │    │(内容/元数据)  │       │
│  └──────────┘    └──────┬───────┘    └──────────────┘       │
│                         │                                     │
│                         │ chunk_hash                          │
│                         ▼                                     │
│                   ┌──────────┐                                │
│                   │ Evidence │  ← Source of Truth             │
│                   └────┬─────┘                                │
│                        │ affected_key                         │
│                        ▼                                     │
│                 ┌──────────────┐                              │
│                 │GraphSyncTask │                              │
│                 └──────────────┘                              │
└──────────────────────────────────────────────────────────────┘
                         │
                         │ Graph Worker
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                         Neo4j                                 │
│  ┌────────┐    ┌──────────┐    ┌───────────┐    ┌──────────┐│
│  │ Entity │───→│  Fact    │←───│ Entity    │   │ Attribute ││
│  │(节点)   │    │(关系节点)  │    │(节点)      │   │(属性节点)  ││
│  └────────┘    └────┬─────┘    └───────────┘    └──────────┘│
│                      │                                        │
│                      │ HAS_ATTRIBUTE                          │
│                      ▼                                        │
│                 ┌───────────┐                                 │
│                 │ Attribute  │                                 │
│                 │(关系属性)   │                                 │
│                 └───────────┘                                 │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                        Milvus                                 │
│  ┌──────────────┐                                             │
│  │ ChunkContent │  text + embedding (1024d)                    │
│  │    Vectors   │                                              │
│  └──────────────┘                                             │
└──────────────────────────────────────────────────────────────┘
```

---

# Part B: 数据模型详情

## B.1 Document 表

```sql
CREATE TABLE document (
    doc_id TEXT PRIMARY KEY,
    doc_version INTEGER NOT NULL DEFAULT 1,
    doc_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    folder TEXT NOT NULL DEFAULT '/',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE | DELETED | PROCESSING
    processing_stage TEXT NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    processing_time_ms REAL NOT NULL DEFAULT 0,
    error TEXT,
    file_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**与当前 `documents` 表差异**：新增 `doc_version` 和 `doc_hash` 字段；`status` 增加 `DELETED` 状态。

## B.2 ChunkContent 表（新表）

唯一 Chunk 内容表。同样内容的 Chunk 只保留一份。

```sql
CREATE TABLE chunk_content (
    chunk_hash TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    milvus_id TEXT,
    ref_count INTEGER NOT NULL DEFAULT 0,  -- 从 DocChunkRef 派生
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
```

## B.3 DocChunkRef 表（新表）

Document 与 Chunk 的引用关系。用于增量更新、引用计数、版本管理。

```sql
CREATE TABLE doc_chunk_ref (
    doc_id TEXT NOT NULL,
    doc_version INTEGER NOT NULL,
    chunk_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    page_no INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    is_stale INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (doc_id, doc_version, chunk_hash)
);

CREATE INDEX idx_dcr_chunk_hash ON doc_chunk_ref(chunk_hash, active);
CREATE INDEX idx_dcr_doc_id ON doc_chunk_ref(doc_id, active, is_stale);
```

## B.4 Evidence 表（新表）

原子知识证据。Evidence 绑定 Chunk，不绑定 Document。Source of Truth。

```sql
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    chunk_hash TEXT NOT NULL,

    evidence_type TEXT NOT NULL,
    -- ENTITY | ENTITY_ATTRIBUTE | FACT | FACT_ATTRIBUTE

    -- Entity evidence
    entity_key TEXT,
    entity_name TEXT,
    entity_type TEXT,

    -- Fact evidence
    subject_key TEXT,
    subject_name TEXT,
    subject_type TEXT,
    predicate TEXT,
    object_key TEXT,
    object_name TEXT,
    object_type TEXT,

    -- Attribute evidence
    attr_owner_type TEXT,     -- ENTITY | FACT
    attr_key TEXT,
    attr_value TEXT,

    evidence_text TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,

    extractor_version TEXT,

    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 索引
CREATE INDEX idx_ev_chunk ON evidence(chunk_hash, active);
CREATE INDEX idx_ev_type ON evidence(active, evidence_type);
CREATE INDEX idx_ev_entity ON evidence(entity_key, active);
CREATE INDEX idx_ev_fact ON evidence(subject_key, predicate, object_key, active);
CREATE INDEX idx_ev_entity_attr ON evidence(entity_key, attr_key, attr_value, active);
CREATE INDEX idx_ev_fact_attr ON evidence(subject_key, predicate, object_key, attr_key, attr_value, active);
```

## B.5 GraphSyncTask 表（新表）

保证 Neo4j 最终一致性的任务队列。

```sql
CREATE TABLE graph_sync_task (
    task_id TEXT PRIMARY KEY,
    doc_id TEXT,
    doc_version INTEGER,
    chunk_hash TEXT,
    affected_key TEXT NOT NULL,
    affected_type TEXT NOT NULL,   -- ENTITY | FACT | ENTITY_ATTRIBUTE | FACT_ATTRIBUTE
    operation TEXT NOT NULL,       -- UPSERT | DELETE
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | PROCESSING | SUCCESS | FAILED
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_gst_status ON graph_sync_task(status);
```

## B.6 唯一键定义

| 对象 | Key 格式 | 示例 |
|------|---------|------|
| Entity Key | `entity_type:normalized_name` | `company:阿里巴巴` |
| Fact Key | `subject_key\|predicate\|object_key` | `person:马云\|FOUNDED\|company:阿里巴巴` |
| Entity Attr Key | `entity_key\|attr_key\|attr_value` | `company:阿里巴巴\|headquarter\|杭州` |
| Fact Attr Key | `fact_key\|attr_key\|attr_value` | `person:马云\|FOUNDED\|company:阿里巴巴\|year\|1999` |

---

# Part C: Evidence 类型与语义

## C.1 Evidence 四类

| 类型 | 语义 | 示例 |
|------|------|------|
| `ENTITY` | 某个 Chunk 支持某个实体存在 | `{"entity_key":"person:马云", ...}` |
| `ENTITY_ATTRIBUTE` | 某个 Chunk 支持实体的属性值 | `{"entity_key":"company:阿里巴巴", "attr_key":"headquarter", "attr_value":"杭州"}` |
| `FACT` | 某个 Chunk 支持两个实体间的关系 | `{"subject_key":"person:马云", "predicate":"FOUNDED", "object_key":"company:阿里巴巴"}` |
| `FACT_ATTRIBUTE` | 某个 Chunk 支持某关系的属性 | `{"subject_key":"person:马云", "predicate":"FOUNDED", "object_key":"company:阿里巴巴", "attr_key":"year", "attr_value":"1999"}` |

## C.2 Chunk → Evidence 关系

一个 Chunk 产生多个 Evidence：

```
Chunk_001: "马云于1999年在杭州创立阿里巴巴"
  ├── E1: ENTITY        person:马云
  ├── E2: ENTITY        company:阿里巴巴
  ├── E3: ENTITY        location:杭州
  ├── E4: FACT          person:马云 | FOUNDED | company:阿里巴巴
  ├── E5: FACT_ATTRIBUTE  FOUNDED | year | 1999
  ├── E6: FACT_ATTRIBUTE  FOUNDED | location | 杭州
  └── E7: ENTITY_ATTRIBUTE company:阿里巴巴 | headquarter | 杭州
```

## C.3 Evidence → Neo4j 聚合

```
Entity.support_count
  = COUNT(EVIDENCE WHERE active=1 AND evidence_type='ENTITY' AND entity_key=?)

Fact.support_count
  = COUNT(EVIDENCE WHERE active=1 AND evidence_type='FACT' AND subject_key=? AND predicate=? AND object_key=?)

EntityAttribute.support_count
  = COUNT(EVIDENCE WHERE active=1 AND evidence_type='ENTITY_ATTRIBUTE' AND entity_key=? AND attr_key=? AND attr_value=?)

FactAttribute.support_count
  = COUNT(EVIDENCE WHERE active=1 AND evidence_type='FACT_ATTRIBUTE' AND subject_key=? AND predicate=? AND object_key=? AND attr_key=? AND attr_value=?)
```

---

# Part D: Neo4j 图模型

## D.1 节点模型

```cypher
-- Entity 节点
(:Entity {
    entity_key: "company:阿里巴巴",    -- 唯一
    name: "阿里巴巴",
    type: "Company",
    support_count: 12,
    active: true
})

-- Fact 节点（关系节点化，支持关系属性）
(:Fact {
    fact_key: "person:马云|FOUNDED|company:阿里巴巴",  -- 唯一
    subject_key: "person:马云",
    predicate: "FOUNDED",
    object_key: "company:阿里巴巴",
    support_count: 7,
    active: true
})

-- Attribute 节点
(:Attribute {
    attr_full_key: "company:阿里巴巴|headquarter|杭州",  -- 唯一
    owner_key: "company:阿里巴巴",
    owner_type: "ENTITY",             -- ENTITY | FACT
    key: "headquarter",
    value: "杭州",
    support_count: 5,
    confidence_avg: 0.93,
    is_primary: true,
    active: true
})
```

## D.2 关系模型

```cypher
-- Entity ← → Fact
(:Entity {entity_key:"person:马云"})
  -[:SUBJECT_OF]->
    (:Fact {fact_key:"person:马云|FOUNDED|company:阿里巴巴"})
      -[:OBJECT_OF]->
        (:Entity {entity_key:"company:阿里巴巴"})

-- Entity / Fact → Attribute
(:Entity {entity_key:"company:阿里巴巴"})
  -[:HAS_ATTRIBUTE]->
    (:Attribute {attr_full_key:"company:阿里巴巴|headquarter|杭州"})

(:Fact {fact_key:"..."})
  -[:HAS_ATTRIBUTE]->
    (:Attribute {attr_full_key:"...|year|1999"})
```

**为什么 Fact 要节点化**：Neo4j 的 Relationship 不能关联属性节点。将关系表达为 Fact 中间节点后，`(:Fact)-[:HAS_ATTRIBUTE]->(:Attribute)` 才能实现。

## D.3 属性冲突处理

同一属性 key 允许多个候选 value，通过 `is_primary` 标记主值：

```text
Attribute(company:阿里巴巴, headquarter, 杭州, support_count=5, is_primary=true)
Attribute(company:阿里巴巴, headquarter, 北京, support_count=1, is_primary=false)
```

主值选择规则优先级：
1. `support_count` 最大
2. `confidence_avg` 最高
3. `updated_at` 最新

仅在主值 support_count 归零时切换备选。

---

# Part E: 增量更新流程

## E.1 新增文档

```
1. 文档上传, 创建 Document(doc_version=1)
2. 切分文档 → chunks[]
3. 计算 chunk_hash
4. 每个 chunk:
   a. 查 chunk_content(chunk_hash):
      - 存在 → 复用, 跳至 4c
      - 不存在 → 创建 ChunkContent → Embedding → 写入 Milvus
   b. Evidence Extraction (LLM)
   c. 写入 SQLite Evidence
   d. 更新 chunk_content.ref_count (从 DocChunkRef 重算)
5. 创建 DocChunkRef 记录 (doc_id, doc_version=1, chunk_hash, chunk_index)
6. 收集 affected_keys → 生成 GraphSyncTask
7. Graph Worker 处理:
   a. 对每个 affected_key 从 SQLite 重算 support_count
   b. support_count > 0 → Neo4j UPSERT (active=true)
   c. support_count = 0 → Neo4j active=false
8. 更新 graph_sync_task.status = SUCCESS
```

## E.2 更新文档（Mark-And-Sweep）

```
Step 1: 标记旧引用
  UPDATE doc_chunk_ref SET is_stale = 1 WHERE doc_id = ? AND active = 1

Step 2: 重新切分文档 → new_chunks[], 计算 chunk_hash

Step 3: 逐 Chunk 处理

  ┌─ Case 1: 当前文档已引用 (doc_id, chunk_hash) 存在
  │   → 取消 is_stale=0, 更新 chunk_index
  │   → 无需 Embedding, 无需抽取 Evidence
  │
  ├─ Case 2: ChunkContent 已存在，但未被当前文档引用
  │   → 新建 DocChunkRef
  │   → 若 ref_count 从 0→1：
  │       证据恢复: UPDATE evidence SET active=1 WHERE chunk_hash=?
  │       触发 Neo4j 增量恢复 (生成 GraphSyncTask)
  │   → 无需 Embedding, 无需抽取 Evidence
  │
  └─ Case 3: 全新 Chunk
      → 创建 ChunkContent → Embedding → 写入 Milvus
      → Evidence Extraction → 写入 SQLite
      → 生成 GraphSyncTask

Step 4: 清理 Stale 引用
  UPDATE doc_chunk_ref SET active=0 WHERE is_stale=1 AND doc_id=?
  
Step 5: 处理 1→0 的 Chunk (ref_count 归零)
  对每个 ref_count==0 的 chunk:
    → Evidence 停用: UPDATE evidence SET active=0 WHERE chunk_hash=?
    → 收集受影响对象 → 重算 support_count → Neo4j 更新
    → ChunkContent.active = false (软删除)

Step 6: 更新 Document 版本号
  UPDATE document SET doc_version = doc_version + 1, doc_hash = new_hash
```

## E.3 删除文档

```
1. UPDATE document SET status = 'DELETED'
2. 对文档的所有 DocChunkRef:
   a. UPDATE doc_chunk_ref SET active = 0
3. 对每个引用的 chunk:
   a. ref_count = SELECT COUNT(*) FROM doc_chunk_ref WHERE chunk_hash=? AND active=1
   b. 若 ref_count == 0:
      - Evidence 停用: UPDATE evidence SET active=0 WHERE chunk_hash=?
      - 收集受影响对象 → 重算 support_count → 生成 GraphSyncTask
      - ChunkContent.active = false (软删除)
4. Graph Worker 同步 Neo4j
5. 可选: 物理删除 Milvus 向量 + ChunkContent (定期 GC)
```

## E.4 Chunk 引用计数

不在 `chunk_content` 表中直接维护 ref_count 字段值。

通过 DocChunkRef 实时聚合：

```sql
SELECT COUNT(*) FROM doc_chunk_ref
WHERE chunk_hash = ? AND active = 1
```

**为什么不用 `ref_count += 1` / `ref_count -= 1`**：任务可能失败/重试/重复执行，增量操作会累积误差。从 Source of Truth 重算保证绝对正确。

---

# Part F: Evidence → Neo4j 同步

## F.1 Support Count 重算 SQL

```sql
-- Entity
SELECT COUNT(*) FROM evidence
WHERE active = 1 AND evidence_type = 'ENTITY' AND entity_key = ?;

-- Fact
SELECT COUNT(*) FROM evidence
WHERE active = 1 AND evidence_type = 'FACT'
AND subject_key = ? AND predicate = ? AND object_key = ?;

-- Entity Attribute
SELECT COUNT(*) FROM evidence
WHERE active = 1 AND evidence_type = 'ENTITY_ATTRIBUTE'
AND entity_key = ? AND attr_key = ? AND attr_value = ?;

-- Fact Attribute
SELECT COUNT(*) FROM evidence
WHERE active = 1 AND evidence_type = 'FACT_ATTRIBUTE'
AND subject_key = ? AND predicate = ? AND object_key = ?
AND attr_key = ? AND attr_value = ?;
```

## F.2 Neo4j 更新规则

| support_count | 操作 |
|---------------|------|
| > 0 | MERGE 节点/关系, SET `active=true, support_count=N` |
| = 0 | SET `active=false` (开发阶段保留，不做物理删除) |

## F.3 一致性校验

定期对比 SQLite Evidence 与 Neo4j 的 `support_count` 和 `active` 状态。

发现不一致 → 以 SQLite 为准 → 执行 Repair 重新同步 Neo4j。

---

# Part G: 实现计划

## Phase 1: Evidence 基础层（Day 1-4）

**文件变更：**
- `src/storage/doc_store.py`：新增 `chunk_content`、`doc_chunk_ref`、`evidence`、`graph_sync_task` 表创建
- `src/knowledge_graph/evidence.py`（新）：Evidence dataclass 定义 (4 类型)
- `src/knowledge_graph/evidence_writer.py`（新）：
  - `insert_evidence_batch(chunk_hash, items) → list[evidence_id]`
  - `deactivate_by_chunk(chunk_hash) → list[affected_key]`
  - `get_affected_keys(chunk_hash) → dict[affected_type, set[key]]`
  - `recount_support_count(key, affected_type) → int`

## Phase 2: 抽取器升级（Day 5-7）

**文件变更：**
- `config/prompts.py`：新增 `EVIDENCE_EXTRACTION_SYSTEM` + few-shot example（输出 4 类 evidence JSON）
- `src/knowledge_graph/entity_extractor.py`：
  - 新增 `extract_evidence(text) → list[Evidence]`（LLM 输出 4 类证据 + confidence）
  - 保留旧 `extract()` 方法，通过 `settings.use_evidence_model` 开关控制
- 新增 `extract_evidence_from_chunks(chunks) → list[Evidence]`

## Phase 3: Neo4j 图模型升级（Day 8-11）

**文件变更：**
- `src/knowledge_graph/neo4j_manager.py`：
  - 新增 `init_evidence_schema()`：创建 Entity/Fact/Attribute 约束和索引
  - 新增 `sync_entity(entity_key)` / `sync_fact(fact_key)` / `sync_attribute(attr_full_key)`
  - 新增 `sync_batch(affected_keys)`: 批量同步 Neo4j
  - 新增 `verify_consistency()`: 对比 SQLite vs Neo4j 的 support_count
  - 保留旧 `batch_import()` 方法（过渡期）
- `src/knowledge_graph/graph_sync_worker.py`（新）：
  - 消费 `graph_sync_task` 队列，批量调用 `sync_batch()`
  - 支持重试（retry_count < 3）
  - 标记 SUCCESS / FAILED

## Phase 4: 写入流程重构（Day 12-14）

**文件变更：**
- `api/routes/documents.py`：
  - `_process_document()` 改为 Evidence 驱动流程
  - 新增 `_process_chunk_with_evidence(chunk)` 内部方法
  - `delete_document()` 改为 ref_count 驱动流程
- `src/knowledge_graph/chunk_manager.py`（新）：
  - `create_or_reuse_chunk(text) → chunk_hash`: 查重 → 复用或创建 ChunkContent
  - `update_doc_chunk_refs(doc_id, doc_version, chunks)`: Mark-And-Sweep 流程
  - `process_ref_count_changes(chunk_hashes)`: 处理 0→1 和 1→0 变化

## Phase 5: LightRAG 索引增量更新（Day 15-16）

**文件变更：**
- `src/retrieval/entity_index.py`：
  - 新增 `upsert_entity(entity_key, name, type, description)`
  - 新增 `delete_entity(entity_key)`
  - 数据源从读 Neo4j 改为读 Evidence (SQLite)
- `src/retrieval/relation_index.py`：
  - 新增 `upsert_relation(subject, predicate, object)`
  - 新增 `delete_relation(fact_key)`
- `scripts/build_lightrag_index.py`：
  - 新增 `--incremental` 模式（仅同步变更的 entity/relation）

## Phase 6: 冲突处理 + 软删除 GC（Day 17-18）

**文件变更：**
- `src/knowledge_graph/attribute_resolver.py`（新）：
  - `resolve_primary(entity_key, attr_key)`：选 support_count 最大的 attribute
  - `update_primary_on_change(entity_key, attr_key)`：主值 support_count 归零时切换
- `src/storage/gc.py`（新）：
  - 定期清理 `active=0` 的 ChunkContent（超过 TTL 的），删除 Milvus 向量
  - 定期清理 `status=SUCCESS` 且超过保留期的 GraphSyncTask

## Phase 7: 测试 + 迁移 + 切换（Day 19-21）

- `tests/test_evidence_writer.py`：Evidence 读写、停用、重算
- `tests/test_chunk_manager.py`：Mark-And-Sweep 流程、Chunk 复用、ref_count 变化
- `tests/test_graph_sync.py`：GraphSyncTask 消费、Neo4j 同步、一致性校验
- `scripts/migrate_kg_to_evidence.py`：从旧 Neo4j 数据反向生成 Evidence + 重建新模型
- `docs/` 下更新 AGENTS.md 和 ARCHITECTURE.md

---

# Part H: 当前架构差异清单

| 维度 | 当前 | 目标 | 变更级别 |
|------|------|------|---------|
| **Chunk 去重** | 无 (每个 doc 独立切分) | ChunkContent hash 去重, 多文档共享 | 新增表 |
| **Doc-Chunk 引用** | 隐含在 documents.db | DocChunkRef 明确定义, 支持 Mark-And-Sweep | 新增表 |
| **文档版本** | 无 | doc_version + doc_hash | 新增字段 |
| **Evidence 层** | 无 | SQLite evidence 表, 4 种类型 | 核心新增 |
| **实体主键** | `name` | `entity_type:normalized_name` | 重写 |
| **实体属性** | 平铺字段 (type, description) | 独立 Attribute 节点, support_count, is_primary | 重写 |
| **关系建模** | `(:Entity)-[:RELATES_TO {type}]->(:Entity)` | `(:Entity)-[:SUBJECT_OF]->(:Fact)-[:OBJECT_OF]->(:Entity)` | 重写 |
| **关系属性** | 无 | `(:Fact)-[:HAS_ATTRIBUTE]->(:Attribute)` | 新增 |
| **Support Count** | 无 | SQLite COUNT(active evidence) 派生 | 新增 |
| **冲突处理** | 无 (MERGE 覆盖) | 多候选保留 + is_primary 标记 | 新增 |
| **删除粒度** | doc 级 DETACH DELETE | chunk 级 evidence 停用 + 局部重算 | 重写 |
| **Graph Sync** | 同步 (LLM → Neo4j) | 异步 (GraphSyncTask 队列) | 新增 |
| **一致性校验** | 无 | SQLite vs Neo4j 定期对比 + Repair | 新增 |
| **LightRAG 索引** | 全量重建 (读 Neo4j) | 增量更新 (读 Evidence) | 优化 |
| **抽取器输出** | `{entities, relations}` (2 类) | `[Evidence]` (4 类 + confidence) | 重写 |

---

# Part I: 过渡策略

```
Phase 1-3 期间: settings.use_evidence_model = False
  → 新旧双写: 旧流程正常运行, 新代码逐步构建

Phase 4 完成后: settings.use_evidence_model = True
  → 切换到 Evidence 驱动模式

Phase 7 完成后:
  → 删除旧 EntityExtractor.extract() 方法
  → 删除旧 Neo4j batch_import() 方法
  → 删除旧 Milvus chunk collection 中的冗余字段
```

---

# Part J: 可保留模块（不受影响）

以下模块不需变更：

- `MilvusVectorRetriever` / `BM25Retriever` / `HybridRetriever` / `Reranker`
- `LightRAGRetriever`（数据来源从 Neo4j 换为 Evidence，接口不变）
- `LangGraph workflow` / `query_router` / `answer_validator` / `chitchat`
- `document_parser/` (MinerU, PaddleOCR-VL, table/chart)
- `chunker/` (HierarchicalChunker, TableChunker, ContextMerger)
- `embeddings/` (BGE-M3)
- `llm/` (DeepSeek)
- `config/settings.py` (只新增配置项)
- `frontend/`

---

# 总结

```
Document 是业务对象
ChunkContent 是去重后的内容单元
DocChunkRef 是 Document → Chunk 的桥梁
Evidence 是知识事实的 Source of Truth
Neo4j 是 Evidence 聚合后的 Materialized View
GraphSyncTask 保证 Neo4j 最终一致性
```

系统最终保证：

```
知识图谱内容
严格等于
当前有效文档集合可支持的知识事实集合
```
