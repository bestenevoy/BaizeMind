from typing import Any

from langchain_core.messages import AIMessage

from src.llm.deepseek import get_chat_llm
from src.retrieval.hybrid_retriever import HybridRetriever
from config.settings import settings


def _finalize_merge(base: dict, texts: list[str], ids: list[str], scores: list[float]) -> dict:
    """把合并组的文本/ID/分数写回 base，返回代表条目。"""
    out = dict(base)
    out["text"] = "\n\n".join(texts)
    out["chunk_id"] = "+".join(ids) if len(ids) > 1 else (ids[0] if ids else "")
    out["merged_chunks"] = ids
    out["rerank_score"] = max(scores) if scores else 0.0
    return out


class RetrievalAgent:
    def __init__(self, retriever: HybridRetriever = None):
        self._retriever = retriever or HybridRetriever()
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def search(
        self,
        query: str,
        top_k: int | None = None,
        doc_ids: list[str] | None = None,
        dense_query: str | None = None,
        bm25_query: str | None = None,
    ) -> list[dict[str, Any]]:
        if top_k is None:
            top_k = settings.hybrid_top_k
        results, _ = self._retriever.retrieve(
            query, top_k=top_k, doc_ids=doc_ids,
            dense_query=dense_query, bm25_query=bm25_query,
        )
        return self._dedup_by_chunk_id(results)

    @staticmethod
    def _dedup_by_chunk_id(results: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for r in results:
            cid = r.get("chunk_id", "")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(r)
            elif not cid:
                out.append(r)
        return out

    @staticmethod
    def _dedup_by_text(results: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for r in results:
            text = r.get("text", "").strip()
            h = hash(text)
            if h not in seen:
                seen.add(h)
                out.append(r)
        return out

    @staticmethod
    def _merge_adjacent_chunks(results: list[dict], max_merge_chars: int = 2000) -> list[dict]:
        """检索后合并：同一文档内 chunk_index 相邻（或 chunk_id 序号相邻）的命中
        chunk 拼接成一条，恢复原始连续上下文。合并后保留最高分作为代表分数，
        chunk_id 用 `+` 串联标记，`merged_chunks` 记录原始 ID 列表。

        仅合并相邻（差 1）的 chunk；非相邻或跨文档不合并。
        """
        if len(results) <= 1:
            return results

        def _idx(r: dict) -> int | None:
            # 优先用 metadata.chunk_index，回退到 chunk_id 末尾序号
            mi = r.get("metadata", {}).get("chunk_index")
            if mi is not None:
                return int(mi)
            cid = r.get("chunk_id", "")
            if "_chunk_" in cid:
                try:
                    return int(cid.rsplit("_chunk_", 1)[1])
                except (ValueError, IndexError):
                    pass
            return None

        def _doc(r: dict) -> str:
            return r.get("doc_id", "")

        # 按文档分组，每组内按 chunk_index 排序
        groups: dict[str, list[dict]] = {}
        for r in results:
            groups.setdefault(_doc(r), []).append(r)
        for doc_id in groups:
            groups[doc_id].sort(key=lambda r: (_idx(r) if _idx(r) is not None else 1e9))

        merged_out: list[dict] = []
        for doc_id, items in groups.items():
            if not items:
                continue
            cur = dict(items[0])
            cur_texts = [items[0].get("text", "")]
            cur_ids = [items[0].get("chunk_id", "")]
            cur_scores = [items[0].get("rerank_score", items[0].get("score", 0.0))]
            cur_idx = _idx(items[0])

            for nxt in items[1:]:
                nxt_idx = _idx(nxt)
                nxt_text = nxt.get("text", "")
                # 相邻判定：chunk_index 差 1（两端都有 index 时）
                adjacent = (
                    cur_idx is not None
                    and nxt_idx is not None
                    and nxt_idx - cur_idx == 1
                )
                # 合并后不超长才合并
                would_len = len("\n\n".join(cur_texts + [nxt_text]))
                if adjacent and would_len <= max_merge_chars:
                    cur_texts.append(nxt_text)
                    cur_ids.append(nxt.get("chunk_id", ""))
                    cur_scores.append(nxt.get("rerank_score", nxt.get("score", 0.0)))
                    cur_idx = nxt_idx
                else:
                    # 收尾当前合并组
                    merged_out.append(_finalize_merge(cur, cur_texts, cur_ids, cur_scores))
                    cur = dict(nxt)
                    cur_texts = [nxt_text]
                    cur_ids = [nxt.get("chunk_id", "")]
                    cur_scores = [nxt.get("rerank_score", nxt.get("score", 0.0))]
                    cur_idx = nxt_idx
            merged_out.append(_finalize_merge(cur, cur_texts, cur_ids, cur_scores))

        # 保持一个稳定顺序：按代表分数降序
        merged_out.sort(
            key=lambda r: r.get("rerank_score", r.get("score", 0.0)),
            reverse=True,
        )
        return merged_out

    def extract_context(self, results: list[dict]) -> str:
        deduped = self._dedup_by_text(self._dedup_by_chunk_id(results))
        merged = self._merge_adjacent_chunks(deduped)
        parts = []
        for i, r in enumerate(merged):
            source = f"[{i + 1}]"
            # sheet_summary doc：text 是摘要，列结构在 sheet_columns 字段
            # 需要把列结构拼到 text 里，让 answer_generator 知道字段名和类型
            text = r.get('text', '')
            if r.get('source_type') == 'sheet_summary':
                cols = r.get('sheet_columns', []) or []
                if cols and '[列结构]' not in text:
                    # 列结构格式化委托给 store.format_columns_for_llm（全系统唯一规范格式）
                    from src.excel_rag.store import format_columns_for_llm
                    col_text = format_columns_for_llm(cols)
                    text = f"{text}\n[列结构]\n{col_text}"
            parts.append(f"{source}\n{text}")
        return "\n\n---\n\n".join(parts)
