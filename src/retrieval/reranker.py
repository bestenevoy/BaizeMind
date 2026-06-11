from typing import Any, Optional

from src.llm.deepseek import get_chat_llm

RERANK_PROMPT = """You are a search result reranker. Given a query and a list of search results,
select the most relevant results and rank them by relevance to the query.

Query: {query}

Search results:
{results_text}

Select the top {top_k} most relevant results (by index number).
Return ONLY a JSON array of integers: [3, 7, 1, ...]"""


class Reranker:
    def __init__(self, llm=None):
        self._llm = llm

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_llm(temperature=0.0)
        return self._llm

    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if len(results) <= top_k:
            return results

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
            return self._score_rerank(query, results)[:top_k]

    @staticmethod
    def _score_rerank(query: str, results: list[dict], top_k: int = 10) -> list[dict]:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        texts = [r["text"] for r in results]
        vec = TfidfVectorizer(stop_words="english").fit([query] + texts)
        q_vec = vec.transform([query])
        t_vec = vec.transform(texts)
        sims = cosine_similarity(q_vec, t_vec).flatten()

        ranked = sorted(
            zip(results, sims), key=lambda x: x[1], reverse=True
        )
        return [r for r, _ in ranked[:top_k]]
