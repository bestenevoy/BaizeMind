import json
import logging
import re
from typing import Any, Optional

import numpy as np
import requests
from sklearn.metrics.pairwise import cosine_similarity

from src.llm.deepseek import get_chat_llm
from src.embeddings.bge_m3 import BGEM3Embedding
from config.settings import settings

logger = logging.getLogger(__name__)

RERANK_PROMPT = """You are a search result reranker. Given a query and a list of search results,
select the most relevant results and rank them by relevance to the query.

Query: {query}

Search results:
{results_text}

Select the top {top_k} most relevant results (by index number).
Return ONLY a JSON array of integers: [3, 7, 1, ...]"""


class Reranker:
    def __init__(self, llm=None, embedding=None):
        self._llm = llm
        self._embedding = embedding

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def _get_embedding(self):
        if self._embedding is None:
            self._embedding = BGEM3Embedding()
        return self._embedding

    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if not results:
            return results

        method = settings.reranker_method

        if method == "embedding":
            logger.info("reranker: using cross-encoder (SiliconFlow/fallback)")
            return self._cross_encoder_rerank(query, results, top_k)
        elif method == "hybrid":
            logger.info("reranker: using hybrid (cross-encoder + LLM)")
            emb_ranked = self._cross_encoder_rerank(query, results, max(top_k, len(results)))
            return self._llm_rerank(query, emb_ranked, top_k)
        else:
            logger.info("reranker: using LLM (DeepSeek)")
            return self._llm_rerank(query, results, top_k)

    def _cross_encoder_rerank(
        self, query: str, results: list[dict], top_k: int
    ) -> list[dict]:
        """Use SiliconFlow reranker API (BAAI/bge-reranker-v2-m3). Falls back to local embedding cosine sim.

        相同 (query, texts, top_k) 命中缓存，避免调试/评测时反复消耗 SiliconFlow 配额。
        """
        api_key = settings.siliconflow_api_key
        if api_key:
            # ── 缓存读取 ──
            # key 包含 model + query + 文档内容 hash + top_n，文档变化自然失效
            cache_hit = None
            cache_key = None
            if settings.cache_enabled:
                from src.cache import get_cache, make_key
                cache = get_cache()
                texts_for_key = [r.get("text", "") for r in results]
                cache_key = make_key(
                    "rerank",
                    settings.siliconflow_rerank_model,
                    query,
                    f"top_n{min(top_k, len(results))}",
                    "\n".join(texts_for_key),
                )
                cached = cache.get(cache_key)
                if cached is not None:
                    try:
                        import json as _json
                        cached_items = _json.loads(cached)
                        # 用缓存的 (index, score) 重建 results，避免 results 引用陈旧
                        if isinstance(cached_items, list) and len(cached_items) <= len(results):
                            out = []
                            for item in cached_items:
                                idx = item.get("index", -1)
                                if 0 <= idx < len(results):
                                    doc = dict(results[idx])
                                    doc["rerank_score"] = item.get("rerank_score", 0)
                                    out.append(doc)
                            if out:
                                cache_hit = out[:top_k]
                                logger.info(
                                    f"reranker: cross-encoder cache hit (key={cache_key[:24]}...)"
                                )
                    except (ValueError, TypeError) as e:
                        logger.debug(f"reranker cache parse failed: {e}")

            if cache_hit is not None:
                return cache_hit

            # ── 调用 SiliconFlow rerank API ──
            try:
                texts = [r.get("text", "") for r in results]
                resp = requests.post(
                    settings.siliconflow_rerank_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.siliconflow_rerank_model,
                        "query": query,
                        "documents": texts,
                        "top_n": min(top_k, len(results)),
                        "return_documents": False,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    reranked = data.get("results", [])
                    if reranked:
                        out = []
                        cached_items = []
                        for item in reranked:
                            idx = item.get("index", 0)
                            if 0 <= idx < len(results):
                                # Copy to avoid mutating the original results list
                                # (same list is referenced in debug info)
                                doc = dict(results[idx])
                                doc["rerank_score"] = item.get("relevance_score", 0)
                                out.append(doc)
                                cached_items.append({"index": idx, "rerank_score": doc["rerank_score"]})
                        logger.info(f"reranker: cross-encoder returned {len(out)} results (top score={out[0].get('rerank_score', 0):.4f})")

                        # ── 写入缓存（仅存 (index, score)，避免存全文） ──
                        if cache_key is not None and cached_items:
                            try:
                                import json as _json
                                cache.set(
                                    cache_key,
                                    _json.dumps(cached_items),
                                    ttl=settings.cache_ttl_seconds,
                                )
                            except (ValueError, TypeError):
                                pass
                        return out[:top_k]
                    else:
                        logger.warning("reranker: cross-encoder API returned empty results, falling back")
                else:
                    logger.warning(f"reranker: cross-encoder API returned status {resp.status_code}, falling back")
            except Exception as e:
                logger.warning(f"reranker: cross-encoder API call failed ({e}), falling back")

        logger.info("reranker: using local BGE-M3 embedding fallback")
        try:
            embedding = self._get_embedding()
            query_vec = embedding.encode_query_dense(query)
            texts = [r.get("text", "") for r in results]
            chunk_vecs = embedding.encode_dense(texts)

            sims = cosine_similarity(
                query_vec.reshape(1, -1), chunk_vecs
            ).flatten()

            for i, sim in enumerate(sims):
                results[i] = dict(results[i])
                results[i]["rerank_score"] = float(max(0.0, sim))

            ranked = sorted(results, key=lambda r: r.get("rerank_score", 0), reverse=True)
            logger.info(f"reranker: local embedding returned {min(top_k, len(ranked))} results")
            return ranked[:top_k]
        except Exception as e:
            logger.warning(f"reranker: local embedding failed ({e}), using TF-IDF fallback")
            return self._tfidf_fallback(query, results, top_k)

    def _llm_rerank(
        self, query: str, results: list[dict], top_k: int
    ) -> list[dict]:
        results_text = "\n".join(
            f"[{i}] {r.get('text', '')[:300]}"
            for i, r in enumerate(results)
        )

        prompt = RERANK_PROMPT.format(
            query=query,
            results_text=results_text,
            top_k=top_k,
        )

        llm = self._get_llm()
        resp = llm.invoke(prompt)
        try:
            indices = json.loads(re.search(r"\[[^\]]*\]", resp.content).group())
            out = [results[i] for i in indices if 0 <= i < len(results)]
            for rank, r in enumerate(out):
                r["rerank_score"] = 1.0 - rank / max(len(out), 1)
            logger.info(f"reranker: LLM rerank returned {len(out)} results")
            return out[:top_k]
        except Exception as e:
            logger.warning(f"reranker: LLM rerank failed ({e}), using TF-IDF fallback")
            return self._tfidf_fallback(query, results, top_k)

    @staticmethod
    def _tfidf_fallback(query: str, results: list[dict], top_k: int = 10) -> list[dict]:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            texts = [r["text"] for r in results]
            vec = TfidfVectorizer(stop_words="english").fit([query] + texts)
            q_vec = vec.transform([query])
            t_vec = vec.transform(texts)
            sims = cosine_similarity(q_vec, t_vec).flatten()

            for i, s in enumerate(sims):
                results[i]["rerank_score"] = float(max(0.0, s))
            ranked = sorted(results, key=lambda r: r.get("rerank_score", 0), reverse=True)
            logger.info(f"reranker: TF-IDF fallback returned {min(top_k, len(ranked))} results")
            return [r for r in ranked[:top_k]]
        except Exception:
            return results[:top_k]
