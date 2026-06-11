# AGENTS.md

## Commands

```bash
# Backend
uv run -m uvicorn api.main:app --host 0.0.0.0 --port 8000   # Start server
uv run -m pytest tests/test_parser.py tests/test_chunker.py tests/test_graph.py -v  # Unit tests (safe, no network)
uv run -m pytest tests/ -v  # ALL tests — WARNING: test_retrieval.py and test_agents.py::test_workflow_init hang if Milvus/models unavailable

# Frontend
cd frontend && npm run dev      # Dev server on :3000 (proxies /api → :8000)
cd frontend && npx tsc --noEmit # Typecheck
cd frontend && npm run build    # Production build → dist/

# Scripts
uv run python scripts/ingest_documents.py <file>   # Ingest single document
uv run python scripts/build_graph.py               # Build Neo4j knowledge graph
uv run python scripts/build_graphrag.py            # Build Microsoft GraphRAG index
uv run python scripts/run_evaluation.py            # Run eval suite
```

## Architecture Gotchas

- **LangGraph workflow** (`src/agents/workflow.py`): 6 query types route differently — `chitchat` → direct LLM (no retrieval), `holistic` → Microsoft GraphRAG, `multi_hop`/`comparison` → Neo4j graph + retrieval, `simple_fact`/`definition` → retrieval only
- **MinerU CLI** is at `.venv/bin/mineru`, NOT in system PATH. `mineru_parser.py` auto-resolves via `sys.executable.parent`. Do not call bare `mineru` in subprocess.
- **PaddleOCR-VL compat**: `src/document_parser/langchain_compat.py` MUST be imported before any `paddleocr` import — it monkey-patches removed langchain modules that PaddleX depends on
- **BGE-M3 defaults to SiliconFlow API** (`BGE_M3_USE_LOCAL=false`). Local FlagEmbedding requires GPU + model download. Do not set `use_local=True` without confirming GPU availability.
- **Milvus uses `MilvusClient` API** (not deprecated `connections.connect` ORM style)
- **SQLite doc store** (`data/documents.db`): auto-created on import. Stores folder/tag/status metadata. The retrieval pipeline filters by folder/tags via `doc_store.get_doc_ids_by_filter()` → Milvus `doc_id in [...]` filter.

## External Services Required

| Service | Port | Required For |
|---------|------|-------------|
| Milvus Standalone | 19530 | Vector search, document ingestion |
| Neo4j | 7687 (bolt) | Knowledge graph queries, entity extraction |
| DeepSeek API | remote | All LLM calls (chat + reasoning) |
| SiliconFlow API | remote | BGE-M3 embeddings (default) |

Tests that touch Milvus/Neo4j/models will **hang indefinitely** if services are down. Run only `test_parser.py`, `test_chunker.py`, `test_graph.py` for safe offline testing.

## Project Layout

- `config/` — `settings.py` (pydantic-settings, loads `.env`), `prompts.py` (all LLM prompts)
- `src/document_parser/` — MinerU, PaddleOCR-VL-1.5, table/chart parsing
- `src/chunker/` — Hierarchical (heading-based), table-aware, context merging
- `src/embeddings/` — BGE-M3 wrapper (local GPU or SiliconFlow API)
- `src/retrieval/` — Milvus vector, BM25, hybrid RRF fusion, reranker, graph expander
- `src/knowledge_graph/` — Entity extraction (LLM + LangExtract), Neo4j CRUD, Microsoft GraphRAG indexer/query
- `src/agents/` — LangGraph StateGraph: query_router, retrieval_agent, graph_agent, answer_validator, workflow
- `src/storage/` — SQLite doc metadata (folders, tags), auto-tagger
- `src/evaluation/` — 105-sample QA dataset, Recall@K/Accuracy/Citation metrics
- `api/` — FastAPI routes: documents (upload/list/folders/tags), qa (ask/stream), management (stats)
- `frontend/` — React 18 + Vite + Tailwind + shadcn/ui, three-column layout (folders | docs+upload | chat)
- `scripts/` — CLI tools for ingestion, graph building, evaluation

## Conventions

- Python 3.11+, managed with **uv** (not pip). Always use `uv run` or `.venv/bin/python`.
- `numpy>=2.0.0` required — older versions fail to build from source on Python 3.13.
- All config via environment variables in `.env`, loaded by `pydantic-settings`. Never hardcode API keys.
- Prompts are centralized in `config/prompts.py` — edit there, not inline.
- Frontend uses `@/` path alias (→ `./src/`), configured in both `vite.config.ts` and `tsconfig.json`.
- Documentation is in Chinese (`ARCHITECTURE.md`). Code comments mix Chinese and English.
