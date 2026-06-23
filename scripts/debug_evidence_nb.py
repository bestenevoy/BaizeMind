# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
# ---
# %% [markdown]
# # Agentic-RAG Evidence 提取调试 Notebook
#
# 逐步运行每个 cell，查看 LLM 返回的原始 JSON 和解析结果。
# 如果报错，直接在当前 cell 看到完整 traceback。

# %% [markdown]
# ## 1. 环境准备

# %%
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

# %% [markdown]
# ## 2. 选择测试文件（修改这里指向你的文件）

# %%
FILE_PATH = "/home/wrz/code/agentic-rag/data/raw/中华人民共和国劳动法_20181229.docx"

# %% [markdown]
# ## 3. 解析文档 (MinerU)

# %%
from src.document_parser.mineru_parser import MinerUParser

doc_id = Path(FILE_PATH).stem
print(f"Parsing: {FILE_PATH}")

parser = MinerUParser()
result = parser.parse(FILE_PATH, doc_id)
markdown = result.get("markdown", "")
print(f"Markdown: {len(markdown)} chars")
print(f"--- preview (first 300 chars) ---")
print(markdown[:300])

# %% [markdown]
# ## 4. Chunk 切分

# %%
from config.settings import settings
from src.chunker.hierarchical_chunker import HierarchicalChunker
from src.chunker.table_chunker import TableChunker
from src.chunker.context_merger import ContextMerger
from src.document_parser.table_parser import TableParser

h_chunker = HierarchicalChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
chunks = h_chunker.chunk(doc_id, markdown)
tables = TableParser.extract_tables_from_markdown(markdown)
table_chunks = TableChunker().chunk_tables(doc_id, tables)
chunks.extend(table_chunks)
merger = ContextMerger()
chunks = merger.merge(chunks)
chunks = merger.deduplicate(chunks)
chunks = [c for c in chunks if c["text"].strip()]

print(f"Total chunks: {len(chunks)}")
for i, c in enumerate(chunks):
    print(f"  [{i}] {len(c['text'])} chars | {c['text'][:120]}...")

# %% [markdown]
# ## 5. 测试 LLM 原始调用（只看第1个 chunk）

# %%
from src.knowledge_graph.entity_extractor import EntityExtractor
from config.prompts import EVIDENCE_EXTRACTION_SYSTEM, EVIDENCE_EXTRACTION_EXAMPLE

extractor = EntityExtractor()
llm = extractor._get_llm()

# 只测试第一个 chunk
text = chunks[0]["text"][:4000]
print(f"=== Chunk text ({len(text)} chars) ===")
print(text)
print()

prompt = f"{EVIDENCE_EXTRACTION_SYSTEM}\n\nExample:\n{EVIDENCE_EXTRACTION_EXAMPLE}\n\nText: {text}\n\nResponse:"
print(f"=== Prompt ({len(prompt)} chars) ===")
print(prompt[:500], "...")

# %% [markdown]
# ## 6. 🚀 调用 LLM（会消耗 token！）

# %%
import json
import re
import traceback

resp = llm.invoke(prompt)
raw = resp.content
print(f"=== Raw LLM response ({len(raw)} chars) ===")
print(raw)

# %% [markdown]
# ## 7. 解析 LLM 返回

# %%
print("=== Step 1: regex extract JSON ===")
try:
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        json_str = match.group()
        print(f"Extracted JSON ({len(json_str)} chars):")
        print(json_str[:500], "..." if len(json_str) > 500 else "")
    else:
        print("ERROR: No JSON block found!")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()

# %%
print("=== Step 2: json.loads ===")
data = None
try:
    data = json.loads(json_str)
    print(f"Type: {type(data).__name__}")
    if isinstance(data, dict):
        print(f"Keys: {list(data.keys())}")
        ev_items = data.get("evidence_items", "KEY_NOT_FOUND")
        print(f"evidence_items type: {type(ev_items).__name__}")
        if isinstance(ev_items, list):
            print(f"evidence_items count: {len(ev_items)}")
            for i, it in enumerate(ev_items[:5]):
                print(f"  [{i}] type={type(it).__name__}, content={str(it)[:200]}")
        elif isinstance(ev_items, str):
            print(f"evidence_items is STRING: {ev_items[:500]}")
        else:
            print(f"evidence_items is unexpected: {repr(ev_items)[:500]}")
    else:
        print(f"Data is not a dict: {str(data)[:500]}")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()

# %% [markdown]
# ## 8. 防御解析测试

# %%
from src.knowledge_graph.entity_extractor import _parse_evidence_items

print("=== Step 3: _parse_evidence_items ===")
try:
    items = _parse_evidence_items(data)
    print(f"Parsed {len(items)} items")
    for i, it in enumerate(items[:5]):
        print(f"  [{i}] type={type(it).__name__}")
        if isinstance(it, dict):
            print(f"       keys={list(it.keys())[:5]}")
            print(f"       values={str({k: it.get(k) for k in list(it.keys())[:3]})}")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()

# %% [markdown]
# ## 9. 构造 Evidence 对象

# %%
from src.knowledge_graph.evidence import (
    EntityEvidence, EntityAttributeEvidence, FactEvidence, FactAttributeEvidence,
)

chunk_hash = "debug_chunk_test"

print("=== Step 4: Build Evidence objects ===")
evidence_objects = []
for idx, item in enumerate(items):
    try:
        etype = item.get("type", "").upper()
        conf = float(item.get("confidence", 0.5))
        ev_text = text[:200]

        if etype == "ENTITY":
            ev = EntityEvidence(
                chunk_hash=chunk_hash,
                entity_name=item.get("entity_name", ""),
                entity_type=item.get("entity_type", "Unknown"),
                confidence=conf,
                evidence_text=ev_text,
            )
        elif etype == "ENTITY_ATTRIBUTE":
            ev = EntityAttributeEvidence(
                chunk_hash=chunk_hash,
                entity_key=item.get("entity_key", ""),
                attr_key=item.get("attr_key", ""),
                attr_value=item.get("attr_value", ""),
                confidence=conf,
                evidence_text=ev_text,
            )
        elif etype == "FACT":
            ev = FactEvidence(
                chunk_hash=chunk_hash,
                subject_name=item.get("subject_name", ""),
                subject_type=item.get("subject_type", "Unknown"),
                predicate=item.get("predicate", ""),
                object_name=item.get("object_name", ""),
                object_type=item.get("object_type", "Unknown"),
                confidence=conf,
                evidence_text=ev_text,
            )
        elif etype == "FACT_ATTRIBUTE":
            ev = FactAttributeEvidence(
                chunk_hash=chunk_hash,
                subject_key=item.get("subject_key", ""),
                predicate=item.get("predicate", ""),
                object_key=item.get("object_key", ""),
                attr_key=item.get("attr_key", ""),
                attr_value=item.get("attr_value", ""),
                confidence=conf,
                evidence_text=ev_text,
            )
        else:
            print(f"  [{idx}] SKIP unknown type: {etype}")
            continue

        evidence_objects.append(ev)
        print(f"  [{idx}] {etype} → affected_key={ev.affected_key}")
    except Exception as e:
        print(f"  [{idx}] ERROR building evidence: {e}")
        print(f"       item = {item}")
        traceback.print_exc()

print(f"\nTotal evidence objects: {len(evidence_objects)}")

# %% [markdown]
# ## 10. 测试写入 SQLite

# %%
print("=== Step 5: write_evidence ===")
try:
    from src.knowledge_graph.evidence_writer import write_evidence
    result = write_evidence(chunk_hash, evidence_objects)
    print(f"Wrote {result['count']} records")
    print(f"Affected keys by type:")
    for t, keys in result.get("affected_keys", {}).items():
        print(f"  {t}: {len(keys)} keys")
        for k in list(keys)[:3]:
            print(f"    - {k}")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()

# %% [markdown]
# ## 11. 验证 SQLite 中的数据

# %%
print("=== Step 6: Query SQLite ===")
from src.storage import doc_store

conn = doc_store._get_conn()
rows = conn.execute(
    "SELECT evidence_type, COUNT(*) as cnt FROM evidence WHERE chunk_hash = ? AND active = 1 GROUP BY evidence_type",
    (chunk_hash,),
).fetchall()
for r in rows:
    print(f"  {r['evidence_type']}: {r['cnt']}")

sample = conn.execute(
    "SELECT evidence_type, entity_key, subject_key, predicate, object_key, attr_key, attr_value FROM evidence WHERE chunk_hash = ? LIMIT 5",
    (chunk_hash,),
).fetchall()
print("\nSample records:")
for s in sample:
    print(f"  {dict(s)}")
conn.close()

# %% [markdown]
# ## 12. （可选）处理所有 chunk — ⚠️ 会消耗很多 token！

# %%
PROCESS_ALL = False  # 设置为 True 处理全部

if PROCESS_ALL:
    from src.knowledge_graph.chunk_manager import compute_chunk_hash

    total = 0
    errors = 0
    for i, chunk in enumerate(chunks):
        ch = compute_chunk_hash(chunk["text"])
        print(f"\n[{i}/{len(chunks)}] {ch[:12]}... ({len(chunk['text'])} chars)")
        try:
            resp = llm.invoke(
                f"{EVIDENCE_EXTRACTION_SYSTEM}\n\nExample:\n{EVIDENCE_EXTRACTION_EXAMPLE}\n\nText: {chunk['text'][:4000]}\n\nResponse:"
            )
            data = json.loads(re.search(r"\{[\s\S]*\}", resp.content).group())
            items = _parse_evidence_items(data)
            ev_objs = build_evidence_objects(items, ch, chunk["text"])
            if ev_objs:
                write_evidence(ch, ev_objs)
            total += len(ev_objs)
            print(f"  → {len(ev_objs)} items, total={total}")
        except Exception as e:
            print(f"  → ERROR: {e}")
            traceback.print_exc()
            errors += 1
    print(f"\nDone. {total} evidence items, {errors} errors")
else:
    print("Set PROCESS_ALL=True to process all chunks (will consume LLM tokens)")
