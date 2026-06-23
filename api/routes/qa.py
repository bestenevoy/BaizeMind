import json
import logging
import time
import traceback
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.schemas import QARequest, QAResponse
from src.agents.workflow import get_workflow
from src.storage.doc_store import get_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])


@router.post("/ask", response_model=QAResponse)
async def ask(request: QARequest):
    start = time.time()

    try:
        workflow = get_workflow()
        result = workflow.invoke(
            request.query,
            folder=request.folder,
            tags=request.tags,
        )

        elapsed = (time.time() - start) * 1000

        docs = result.get("documents", [])
        doc_name_cache: dict[str, str] = {}
        retrieved_docs = []
        for d in docs[:10]:
            did = d.get("doc_id", "?")
            if did not in doc_name_cache:
                doc = get_document(did)
                doc_name_cache[did] = doc["filename"] if doc else did
            retrieved_docs.append({
                "doc_id": did,
                "chunk_id": d.get("chunk_id", "?"),
                "text": d.get("text", "")[:500],
                "score": d.get("score", 0.0) if isinstance(d.get("score"), (int, float)) else 0.0,
                "filename": doc_name_cache[did],
            })

        return QAResponse(
            query=request.query,
            answer=result.get("final_answer", result.get("draft_answer", "")),
            query_type=result.get("query_type", "simple_fact"),
            confidence=result.get("confidence", 0.0),
            citations=result.get("citations", []),
            graph_context=result.get("graph_context", ""),
            retrieved_docs=retrieved_docs,
            validation=result.get("validation", {}),
            processing_time_ms=elapsed,
        )
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(500, f"QA processing failed: {e}")


NODE_LABELS = {
    "query_router": ("分析问题类型", "问题分类"),
    "chitchat": ("直接对话", "闲聊"),
    "retrieval_agent": ("RAG 向量/BM25检索", "检索结果"),
    "graph_agent": ("知识图谱查询", "图谱上下文"),
    "graphrag_search": ("Microsoft GraphRAG 检索", "GraphRAG 结果"),
    "answer_generator": ("LLM 生成回答", "生成回答"),
    "answer_validator": ("验证回答", "验证结果"),
}


@router.post("/stream", response_class=StreamingResponse)
async def ask_stream(request: QARequest):
    workflow = get_workflow()

    async def event_stream():
        start = time.time()
        try:
            async for event in workflow.astream(
                request.query,
                folder=request.folder,
                tags=request.tags,
            ):
                if not isinstance(event, dict) or not event:
                    logger.warning(f"Skipping non-dict/empty event: {event!r}")
                    continue
                (node_name, node_output), = event.items()
                label, detail_label = NODE_LABELS.get(node_name, (node_name, node_name))

                payload = {"type": "step", "node": node_name, "label": label, "detail": detail_label}

                if node_output.get("error"):
                    payload["status"] = "error"
                    payload["error"] = node_output["error"]
                else:
                    payload["status"] = "done"

                if node_name == "query_router":
                    payload["result"] = {
                        "query_type": node_output.get("query_type", "simple_fact"),
                        "confidence": node_output.get("confidence", 0.0),
                    }
                elif node_name == "retrieval_agent":
                    docs = node_output.get("documents", [])
                    doc_name_cache: dict[str, str] = {}
                    doc_items = []
                    for d in docs[:5]:
                        did = d.get("doc_id", "?")
                        if did not in doc_name_cache:
                            doc = get_document(did)
                            doc_name_cache[did] = doc["filename"] if doc else did
                        doc_items.append({
                            "doc_id": did,
                            "chunk_id": d.get("chunk_id", "?"),
                            "text": d.get("text", "")[:300],
                            "score": d.get("score", 0.0) if isinstance(d.get("score"), (int, float)) else 0.0,
                            "filename": doc_name_cache[did],
                        })
                    payload["result"] = {
                        "count": len(docs),
                        "documents": doc_items,
                    }
                elif node_name == "graph_agent":
                    graph_context = node_output.get("graph_context", "")
                    payload["result"] = {
                        "context": graph_context[:1000],
                        "has_context": bool(graph_context) and graph_context != "No entities found for graph expansion.",
                    }
                elif node_name == "graphrag_search":
                    payload["result"] = {"context": node_output.get("graphrag_context", "")[:1000]}
                elif node_name == "answer_generator":
                    payload["result"] = {
                        "answer": node_output.get("draft_answer", ""),
                        "citations": node_output.get("citations", []),
                    }
                elif node_name == "chitchat":
                    payload["result"] = {"answer": node_output.get("final_answer", "")}
                elif node_name == "answer_validator":
                    validation = node_output.get("validation", {})
                    payload["result"] = {
                        "is_valid": validation.get("is_valid", True),
                        "final_answer": node_output.get("final_answer", ""),
                    }

                yield f"data: {json.dumps(payload, default=str)}\n\n"

            elapsed = (time.time() - start) * 1000
            yield f"data: {json.dumps({'type': 'done', 'processing_time_ms': elapsed})}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
