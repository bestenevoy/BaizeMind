import json
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.schemas import (
    EvalSampleCreate,
    EvalSampleUpdate,
    EvalSampleResponse,
    EvalDatasetImport,
    EvalDatasetGenerate,
    EvalRunRequest,
    EvalResultSummary,
    EvalResultDetail,
)
from config.settings import settings
from src.evaluation.dataset import EvalDataset
from src.evaluation.runner import EvalRunner
from src.storage import doc_store

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])

_dataset = EvalDataset()
_results_dir = Path(settings.evaluation_dir / "results")


def _get_dataset() -> EvalDataset:
    _dataset.load()
    return _dataset


def _list_results() -> list[dict]:
    _results_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(_results_dir.glob("eval_*.json"), reverse=True)
    summaries = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            summaries.append({
                "filename": f.name,
                "timestamp": data.get("total_time_seconds", 0),
                "num_samples": data.get("summary", {}).get("num_samples", 0),
                "recall_at_5": data.get("summary", {}).get("recall_at_5", 0),
                "recall_at_10": data.get("summary", {}).get("recall_at_10", 0),
                "semantic_similarity": data.get("summary", {}).get("semantic_similarity", 0),
                "judge_accuracy": data.get("summary", {}).get("judge_accuracy", 0),
                "citation_accuracy": data.get("summary", {}).get("citation_accuracy", 0),
            })
        except Exception:
            pass
    return summaries


# ── Dataset CRUD ──

@router.get("/dataset", response_model=list[EvalSampleResponse])
def list_dataset():
    ds = _get_dataset()
    return ds.samples


@router.post("/dataset", response_model=EvalSampleResponse)
def add_sample(sample: EvalSampleCreate):
    ds = _get_dataset()
    data = sample.model_dump(exclude_none=True)
    ds.add_sample(data)
    ds.save()
    return data


@router.put("/dataset/{sample_id}", response_model=EvalSampleResponse)
def update_sample(sample_id: str, update: EvalSampleUpdate):
    ds = _get_dataset()
    for i, s in enumerate(ds.samples):
        if s.get("id") == sample_id:
            update_data = update.model_dump(exclude_none=True)
            s.update(update_data)
            ds.save()
            return s
    raise HTTPException(status_code=404, detail=f"Sample {sample_id} not found")


@router.delete("/dataset/{sample_id}")
def delete_sample(sample_id: str):
    ds = _get_dataset()
    initial_len = len(ds.samples)
    ds._samples = [s for s in ds.samples if s.get("id") != sample_id]
    if len(ds.samples) == initial_len:
        raise HTTPException(status_code=404, detail=f"Sample {sample_id} not found")
    ds.save()
    return {"deleted": True, "id": sample_id}


@router.post("/dataset/import")
def import_dataset(body: EvalDatasetImport):
    ds = _get_dataset()
    if body.mode == "replace":
        ds._samples = body.samples
    else:
        ds.add_samples(body.samples)
    ds.save()
    return {"count": len(ds.samples), "mode": body.mode}


@router.get("/dataset/export")
def export_dataset():
    ds = _get_dataset()
    return ds.samples


# ── Dataset Generation from Knowledge Base ──

@router.post("/dataset/generate")
def generate_dataset(req: EvalDatasetGenerate):
    def generate():
        folder = req.folder or "/"
        max_docs = req.max_docs or 10
        samples_per_doc = req.samples_per_doc or 3

        doc_ids = doc_store.get_doc_ids_by_filter(folder=folder)
        if not doc_ids:
            yield f"data: {json.dumps({'type': 'error', 'error': f'No documents found in folder: {folder}'})}\n\n"
            return

        doc_ids = doc_ids[:max_docs]
        yield f"data: {json.dumps({'type': 'start', 'total': len(doc_ids), 'folder': folder})}\n\n"

        try:
            from src.retrieval.vector_retriever import MilvusVectorRetriever
            vr = MilvusVectorRetriever()
            vr.connect()

            all_chunks = vr.fetch_all_chunks()
            chunks_by_doc: dict[str, list[dict]] = {}
            for c in all_chunks:
                did = c.get("doc_id", "")
                if did in doc_ids:
                    chunks_by_doc.setdefault(did, []).append(c)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Failed to fetch chunks: {e}'})}\n\n"
            return

        if not chunks_by_doc:
            yield f"data: {json.dumps({'type': 'error', 'error': 'No chunks found for documents in folder'})}\n\n"
            return

        from src.llm.deepseek import get_chat_llm
        llm = get_chat_llm(temperature=0.3)

        ds = _get_dataset()
        # Get max existing ID to continue numbering
        existing_ids = [s.get("id", "") for s in ds.samples]
        max_num = 0
        for eid in existing_ids:
            try:
                max_num = max(max_num, int(eid))
            except ValueError:
                pass

        generated = []
        doc_idx = 0
        for doc_id, chunks in chunks_by_doc.items():
            doc_idx += 1
            yield f"data: {json.dumps({'type': 'progress', 'current': doc_idx, 'total': len(chunks_by_doc), 'doc_id': doc_id})}\n\n"

            chunk_texts = [c.get("text", "") for c in chunks[:50] if c.get("text", "").strip()]
            if not chunk_texts:
                continue

            combined = "\n---\n".join(chunk_texts[:20])

            prompt = (
                "You are a dataset generator for RAG evaluation. Based on the document content below, "
                f"generate {samples_per_doc} question-answer pairs in diverse query types "
                "(mix of simple_fact, definition, multi_hop, comparison). "
                "Each question should be answerable from the provided content. "
                "Output as JSON array with fields: query, query_type, ground_truth_answer. "
                "Keep answers concise, 1-3 sentences.\n\n"
                f"Document content:\n{combined[:6000]}\n\n"
                "Output ONLY the JSON array, nothing else."
            )

            try:
                resp = llm.invoke(prompt).content
                match = re.search(r"\[[\s\S]*\]", resp)
                if not match:
                    continue
                qa_pairs = json.loads(match.group())
            except Exception:
                continue

            for qa in qa_pairs:
                max_num += 1
                sample = {
                    "id": str(max_num).zfill(3),
                    "query": qa.get("query", ""),
                    "query_type": qa.get("query_type", "simple_fact"),
                    "ground_truth_answer": qa.get("ground_truth_answer", ""),
                    "ground_truth_sources": [doc_id],
                    "ground_truth_ids": [c.get("chunk_id", "") for c in chunks[:5]],
                }
                generated.append(sample)
                yield f"data: {json.dumps({'type': 'sample_generated', 'sample_id': sample['id'], 'query': sample['query'][:80]})}\n\n"

        if generated:
            if req.mode == "replace":
                ds._samples = generated
            else:
                ds.add_samples(generated)
            ds.save()

        yield f"data: {json.dumps({'type': 'done', 'count': len(generated), 'mode': req.mode})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Run Evaluation ──

@router.post("/run")
def run_evaluation(req: EvalRunRequest):
    def generate():
        ds = _get_dataset()
        samples = ds.samples
        if req.max_samples:
            samples = samples[:req.max_samples]

        runner = EvalRunner()
        runner.dataset._samples = samples  # pre-loaded

        results = []
        start = time.time()

        yield f"data: {json.dumps({'type': 'start', 'total': len(samples)})}\n\n"

        # Pre-compile workflow once
        workflow = None
        try:
            from src.agents.workflow import get_workflow
            workflow = get_workflow()
        except Exception:
            pass

        for i, sample in enumerate(samples):
            yield f"data: {json.dumps({'type': 'progress', 'current': i + 1, 'total': len(samples), 'sample_id': sample.get('id', str(i)), 'query': sample['query'][:80]})}\n\n"

            sample_start = time.time()
            try:
                if workflow is None:
                    from src.agents.workflow import get_workflow
                    workflow = get_workflow()
                result = workflow.invoke(sample["query"], folder=req.folder)
                err = None
                predicted = result.get("final_answer", "")
                cited_sources = result.get("citations", [])
                retrieved_ids = [
                    d.get("chunk_id", "") for d in result.get("documents", [])
                ]
                query_type = result.get("query_type", "")
            except Exception as e:
                err = str(e)
                predicted = f"ERROR: {e}"
                cited_sources = []
                retrieved_ids = []
                query_type = ""

            sample_time = (time.time() - sample_start) * 1000
            results.append({
                "sample_id": sample.get("id", str(i)),
                "query": sample["query"],
                "query_type": query_type,
                "predicted_answer": predicted,
                "cited_sources": cited_sources,
                "retrieved_ids": retrieved_ids,
                "error": err,
                "processing_time_ms": sample_time,
            })

            yield f"data: {json.dumps({'type': 'sample_done', 'sample_id': sample.get('id', str(i)), 'processing_time_ms': sample_time, 'error': err})}\n\n"

        elapsed = time.time() - start
        metrics = runner.metrics.compute_metrics(samples, results)

        report = {
            "summary": metrics,
            "total_time_seconds": elapsed,
            "avg_time_per_sample": elapsed / len(samples) if samples else 0,
            "results": results,
        }

        output_path = _results_dir / f"eval_{int(time.time())}.json"
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

        yield f"data: {json.dumps({'type': 'done', 'summary': {**metrics, 'total_time_seconds': elapsed}, 'filename': output_path.name})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Results ──

@router.get("/results", response_model=list[EvalResultSummary])
def list_results():
    return _list_results()


@router.get("/results/{filename}", response_model=EvalResultDetail)
def get_result(filename: str):
    filepath = _results_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Result {filename} not found")
    data = json.loads(filepath.read_text(encoding="utf-8"))
    return data


@router.delete("/results/{filename}")
def delete_result(filename: str):
    filepath = _results_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Result {filename} not found")
    filepath.unlink()
    return {"deleted": True, "filename": filename}
