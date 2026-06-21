from typing import Any, Optional

import numpy as np
import requests
from sklearn.metrics.pairwise import cosine_similarity

from src.llm.deepseek import get_chat_llm
from src.embeddings.bge_m3 import BGEM3Embedding
from config.settings import settings

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
        if len(results) <= top_k:
            return results

        method = settings.reranker_method

        if method == "embedding":
            return self._cross_encoder_rerank(query, results, top_k)
        elif method == "hybrid":
            emb_ranked = self._cross_encoder_rerank(query, results, top_k * 2)
            return self._llm_rerank(query, emb_ranked, top_k)
        else:  # llm
            return self._llm_rerank(query, results, top_k)

    def _cross_encoder_rerank(
        self, query: str, results: list[dict], top_k: int
    ) -> list[dict]:
        """Use SiliconFlow reranker API (BAAI/bge-reranker-v2-m3). Falls back to local embedding cosine sim."""
        api_key = settings.siliconflow_api_key
        if api_key:
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
                        for item in reranked:
                            idx = item.get("index", 0)
                            if 0 <= idx < len(results):
                                results[idx]["rerank_score"] = item.get("relevance_score", 0)
                                out.append(results[idx])
                        return out[:top_k]
            except Exception:
                pass  # Fall through to local embedding

        # Fallback: local BGE-M3 cosine similarity
        try:
            embedding = self._get_embedding()
            query_vec = embedding.encode_query_dense(query)
            texts = [r.get("text", "") for r in results]
            chunk_vecs = embedding.encode_dense(texts)

            sims = cosine_similarity(
                query_vec.reshape(1, -1), chunk_vecs
            ).flatten()

            for i, sim in enumerate(sims):
                results[i]["rerank_score"] = float(max(0.0, sim))

            ranked = sorted(results, key=lambda r: r.get("rerank_score", 0), reverse=True)
            return ranked[:top_k]
        except Exception:
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
            import json, re
            indices = json.loads(re.search(r"\[[^\]]*\]", resp.content).group())
            return [results[i] for i in indices if 0 <= i < len(results)]
        except Exception:
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

            ranked = sorted(
                zip(results, sims), key=lambda x: x[1], reverse=True
            )
            return [r for r, _ in ranked[:top_k]]
        except Exception:
            return results[:top_k]
