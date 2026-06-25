# AGENTS.md

## Commands

```bash
# Backend
uv run -m uvicorn api.main:app --host 0.0.0.0 --port 8000   # Start server (prod)
uv run -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude 'data/*' --reload-exclude '*.log'   # Dev (auto-reload, ignore logs/data to avoid reload loop)
uv run -m pytest tests/test_parser.py tests/test_chunker.py tests/test_graph.py tests/test_evidence.py tests/test_evidence_pipeline.py -v  # Unit tests (safe, no network)
uv run -m pytest tests/ -v  # ALL tests — WARNING: test_retrieval.py and test_agents.py::test_workflow_init hang if Milvus/models unavailable

# Frontend
cd frontend && npm run dev      # Dev server on :3000 (proxies /api → :8000)
cd frontend && npx tsc --noEmit # Typecheck
cd frontend && npm run build    # Production build → dist/

# Scripts
uv run python scripts/ingest_documents.py <file>   # Ingest single document
uv run python scripts/build_graph.py               # Build Neo4j knowledge graph
uv run python scripts/build_lightrag_index.py      # Build LightRAG entity+relation vector indexes (requires Neo4j data first)
uv run python scripts/build_lightrag_index.py --clear      # Clear and rebuild LightRAG indexes
uv run python scripts/migrate_kg_to_evidence.py   # Migrate old Neo4j KG to evidence-driven model
uv run python scripts/migrate_kg_to_evidence.py --dry-run  # Preview migration only
uv run python scripts/build_graphrag.py            # Build Microsoft GraphRAG index
uv run python scripts/run_evaluation.py            # Run eval suite
uv run python scripts/diagnose.py                  # System connectivity diagnostics
```

## Architecture Gotchas

- **LangGraph workflow** (`src/agents/workflow.py`): 6 query types route differently — `chitchat` → direct LLM (no retrieval), `holistic` → retrieval_agent (GraphRAG path is disabled), `multi_hop`/`comparison` → lightrag_agent (with fallback to graph_agent→retrieval if LightRAG indexes empty), `simple_fact`/`definition` with `graph_eligible=True` → lightrag_agent, otherwise → retrieval only
- **Query rewrite** (`settings.query_rewrite_enabled=True`): Before hybrid search, an LLM call rewrites the user query into separate `dense_query` (semantic) and `bm25_query` (keyword) versions. Entity names are appended to BM25 query only, not dense, to preserve semantic vector direction.
- **Evidence-driven KG model** (`src/knowledge_graph/evidence.py`, `evidence_writer.py`): Knowledge graph is now built from an evidence store in SQLite. Evidence types: ENTITY, ENTITY_ATTRIBUTE, FACT, FACT_ATTRIBUTE. Each evidence has `chunk_hash`, `confidence`, and `active` flag. The `GraphSyncTask` queue (`src/knowledge_graph/graph_sync_worker.py`) batch-syncs evidence changes to Neo4j. Chunk dedup via `ChunkContent` (`src/knowledge_graph/chunk_manager.py`).
- **LightRAG fallback** (`src/agents/workflow.py:_node_lightrag_agent`): If `entity_index.count() == 0`, lightrag_agent automatically falls back to `graph_agent → retrieval_agent` to ensure availability without LightRAG indexes.
- **MinerU CLI** is at `.venv/bin/mineru`, NOT in system PATH. `mineru_parser.py` auto-resolves via `sys.executable.parent`. Do not call bare `mineru` in subprocess.
- **PaddleOCR-VL compat**: `src/document_parser/langchain_compat.py` MUST be imported before any `paddleocr` import — it monkey-patches removed langchain modules that PaddleX depends on
- **BGE-M3 defaults to SiliconFlow API** (`BGE_M3_USE_LOCAL=false`). Local FlagEmbedding requires GPU + model download. Do not set `use_local=True` without confirming GPU availability.
- **Milvus uses `MilvusClient` API** (not deprecated `connections.connect` ORM style)
- **SQLite doc store** (`data/documents.db`): auto-created on import. Stores folder/tag/status metadata, ChunkContent dedup, evidence records, GraphSyncTask queue. The retrieval pipeline filters by folder/tags via `doc_store.get_doc_ids_by_filter()` → Milvus `doc_id in [...]` filter.
- **Chunk GC** (`src/storage/gc.py`): Inactive `ChunkContent` records (ref_count=0) are physically deleted after `chunk_gc_ttl_days` (default 30), along with their Milvus vectors.

## External Services Required

| Service | Port | Required For |
|---------|------|-------------|
| Milvus Standalone | 19530 | Vector search, document ingestion |
| Neo4j | 7687 (bolt) | Knowledge graph queries, entity extraction |
| DeepSeek API | remote | All LLM calls (chat + reasoning) |
| SiliconFlow API | remote | BGE-M3 embeddings (default) |

Tests that touch Milvus/Neo4j/models will **hang indefinitely** if services are down. Safe offline tests: `test_parser.py`, `test_chunker.py`, `test_graph.py`, `test_evidence.py`, `test_evidence_pipeline.py` (SQLite only).

## Project Layout

- `config/` — `settings.py` (pydantic-settings, loads `.env`), `prompts.py` (all LLM prompts)
- `src/document_parser/` — MinerU, PaddleOCR-VL-1.5, table/chart parsing
- `src/chunker/` — Hierarchical (heading-based), table-aware, context merging
- `src/embeddings/` — BGE-M3 wrapper (local GPU or SiliconFlow API)
- `src/retrieval/` — Milvus vector, BM25, hybrid RRF fusion, reranker, graph expander, LightRAG (entity/relation indexes + retriever), debug formatter
- `src/knowledge_graph/` — Entity extraction (LLM + LangExtract), Neo4j CRUD, evidence model (4 types: ENTITY/ENTITY_ATTRIBUTE/FACT/FACT_ATTRIBUTE), evidence writer, chunk manager (dedup + ref counting), graph sync worker (Neo4j batch sync), attribute resolver, Microsoft GraphRAG indexer/query
- `src/agents/` — LangGraph StateGraph: query_router, retrieval_agent, graph_agent, answer_validator, workflow
- `src/storage/` — SQLite doc metadata (folders, tags, ChunkContent, evidence, GraphSyncTask), auto-tagger, config overrides, chunk GC
- `src/evaluation/` — 105-sample QA dataset, Recall@K/Accuracy/Citation metrics
- `src/llm/` — DeepSeek LLM wrapper (`deepseek.py`: `get_chat_llm()` for chat, `get_reasoner_llm()` for reasoning)
- `api/` — FastAPI routes: documents (upload/list/folders/tags), qa (ask/stream), management (stats/config/connectivity), evaluation
- `frontend/` — React 18 + Vite + Tailwind + shadcn/ui, three-column layout (folders | docs+upload | chat)
- `scripts/` — CLI tools: ingest_documents, build_graph, build_lightrag_index (entity+relation Milvus indexes from Neo4j), migrate_kg_to_evidence, build_graphrag, run_evaluation, diagnose, setup_milvus.sh

## Performance Optimizations

The ingestion pipeline was analyzed for bottlenecks. Two critical fixes applied:

### 1. Neo4j bulk insert via UNWIND (`src/knowledge_graph/neo4j_manager.py:64-99`)
- **Before**: N entities + M relations = N+M sequential `session.run()` calls (network round-trips)
- **After**: Single `UNWIND $entities AS e MERGE ...` for all entities, single `UNWIND $relations AS r MATCH ... MERGE ...` for all relations — fixed 2 round-trips regardless of scale
- **Speedup**: ~50x for typical documents

### 2. BM25 incremental append (`src/retrieval/bm25_retriever.py:22-44`)
- **Before**: `merge_chunks()` re-tokenized ALL existing chunks via jieba, then rebuilt `BM25Okapi` from scratch
- **After**: Added `_chunk_ids` set for O(1) dedup, only tokenize new chunks, append to `_corpus`, then rebuild `BM25Okapi` (C-level, fast). Avoids repeated jieba tokenization of the entire corpus.
- **Speedup**: ~5-10x for large corpora (saves jieba CPU time, only cost is the unavoidable `BM25Okapi` constructor)

### Remaining bottlenecks (not yet addressed)
- Entity extraction: N sequential LLM calls per document (embarrassingly parallel, ~10-20x potential)
- Embedding batches: sequential HTTP calls per batch (concurrent dispatch possible, ~3-5x potential)
- `chunk_size=512` amplifies all downstream costs (larger chunks = fewer LLM/embedding calls)

## Conventions

- Python 3.11+, managed with **uv** (not pip). Always use `uv run` or `.venv/bin/python`.
- `numpy>=2.0.0` required — older versions fail to build from source on Python 3.13.
- All config via environment variables in `.env`, loaded by `pydantic-settings`. Never hardcode API keys.
- Prompts are centralized in `config/prompts.py` — edit there, not inline.
- Frontend uses `@/` path alias (→ `./src/`), configured in both `vite.config.ts` and `tsconfig.json`.
- Documentation is in Chinese (`ARCHITECTURE.md`). Code comments mix Chinese and English.
