from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from src.embeddings.bge_m3 import BGEM3Embedding
from src.llm.deepseek import get_reasoner_llm


class EvalMetrics:
    def __init__(self):
        self._embedding = BGEM3Embedding()
        self._judge_llm = None

    def _get_judge_llm(self):
        if self._judge_llm is None:
            self._judge_llm = get_reasoner_llm(temperature=0.0)
        return self._judge_llm

    def recall_at_k(self, retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> float:
        if not ground_truth_ids:
            return 0.0
        retrieved = retrieved_ids[:k]
        matched = sum(1 for gt_id in ground_truth_ids if gt_id in retrieved)
        return matched / len(ground_truth_ids)

    def answer_accuracy(self, predicted_answer: str, ground_truth_answer: str) -> float:
        pred_vec = self._embedding.encode_dense([predicted_answer])[0]
        truth_vec = self._embedding.encode_dense([ground_truth_answer])[0]
        sim = cosine_similarity(
            pred_vec.reshape(1, -1), truth_vec.reshape(1, -1)
        )[0][0]
        return float(max(0.0, sim))

    def judge_accuracy(self, predicted_answer: str, ground_truth_answer: str) -> dict[str, Any]:
        llm = self._get_judge_llm()
        prompt = (
            f"Judge if the predicted answer correctly answers the question compared to the ground truth.\n\n"
            f"Predicted: {predicted_answer[:2000]}\n\n"
            f"Ground Truth: {ground_truth_answer[:2000]}\n\n"
            f'Respond in JSON: {{"is_correct": true/false, "semantic_match": 0.0-1.0, '
            f'"completeness": 0.0-1.0, "explanation": "..."}}'
        )
        resp = llm.invoke(prompt)
        try:
            import json, re
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"is_correct": False, "semantic_match": 0.0, "completeness": 0.0, "explanation": "Parse error"}

    def citation_accuracy(self, cited_sources: list[str], ground_truth_sources: list[str]) -> float:
        if not ground_truth_sources:
            return 1.0
        if not cited_sources:
            return 0.0
        matched = sum(1 for src in cited_sources if any(gt in src for gt in ground_truth_sources))
        return matched / max(len(cited_sources), 1)

    def context_relevancy(
        self, query: str, retrieved_texts: list[str]
    ) -> float:
        """Measure how relevant retrieved chunks are to the query.
        Returns average cosine similarity between query and each chunk."""
        if not retrieved_texts:
            return 0.0
        try:
            query_vec = self._embedding.encode_dense([query])[0]
            chunk_vecs = self._embedding.encode_dense(retrieved_texts)
            sims = cosine_similarity(query_vec.reshape(1, -1), chunk_vecs).flatten()
            return float(np.mean(sims))
        except Exception:
            return 0.0

    def context_relevancy_llm(
        self, query: str, retrieved_texts: list[str]
    ) -> float:
        """LLM-judged context relevancy. Rate how much each chunk helps answer the query."""
        if not retrieved_texts:
            return 0.0
        joined = "\n---\n".join(t[:300] for t in retrieved_texts[:10])
        llm = self._get_judge_llm()
        prompt = (
            f"Rate how relevant the retrieved context is to answering the question.\n"
            f"Question: {query[:500]}\n\n"
            f"Retrieved context:\n{joined[:4000]}\n\n"
            f'Respond in JSON: {{"relevancy": 0.0-1.0, "explanation": "..."}}'
        )
        try:
            import json, re
            resp = llm.invoke(prompt)
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                return float(json.loads(match.group()).get("relevancy", 0))
        except Exception:
            pass
        return 0.0

    def answer_relevancy(
        self, query: str, answer: str
    ) -> float:
        """Measure how relevant the answer is to the query.
        Uses LLM judge to score semantic relevance."""
        if not answer:
            return 0.0
        llm = self._get_judge_llm()
        prompt = (
            f"Rate how relevant this answer is to the question, regardless of factual correctness.\n"
            f"Question: {query[:500]}\n\n"
            f"Answer: {answer[:2000]}\n\n"
            f'Respond in JSON: {{"relevancy": 0.0-1.0, "explanation": "..."}}'
        )
        try:
            import json, re
            resp = llm.invoke(prompt)
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                return float(json.loads(match.group()).get("relevancy", 0))
        except Exception:
            pass
        return 0.0

    def compute_metrics(
        self,
        samples: list[dict],
        results: list[dict],
    ) -> dict[str, float]:
        all_recall_5 = []
        all_recall_10 = []
        all_accuracies = []
        all_citations = []
        all_is_correct = []
        all_ctx_relevancy = []
        all_ans_relevancy = []

        for sample, result in zip(samples, results):
            if "retrieved_ids" in result and "ground_truth_ids" in sample:
                all_recall_5.append(
                    self.recall_at_k(result["retrieved_ids"], sample["ground_truth_ids"], 5)
                )
                all_recall_10.append(
                    self.recall_at_k(result["retrieved_ids"], sample["ground_truth_ids"], 10)
                )

            judge = self.judge_accuracy(
                result.get("predicted_answer", ""),
                sample.get("ground_truth_answer", ""),
            )
            sim = self.answer_accuracy(
                result.get("predicted_answer", ""),
                sample.get("ground_truth_answer", ""),
            )
            all_accuracies.append(sim)
            all_is_correct.append(1.0 if judge.get("is_correct") else 0.0)

            cit = self.citation_accuracy(
                result.get("cited_sources", []),
                sample.get("ground_truth_sources", []),
            )
            all_citations.append(cit)

            # Context relevancy from retrieved texts
            retrieved_texts = result.get("retrieved_texts", [])
            if retrieved_texts:
                all_ctx_relevancy.append(
                    self.context_relevancy(sample["query"], retrieved_texts)
                )

            # Answer relevancy
            predicted = result.get("predicted_answer", "")
            if predicted and "error" not in predicted.lower():
                all_ans_relevancy.append(
                    self.answer_relevancy(sample["query"], predicted)
                )

        return {
            "num_samples": len(samples),
            "recall_at_5": float(np.mean(all_recall_5)) if all_recall_5 else 0.0,
            "recall_at_10": float(np.mean(all_recall_10)) if all_recall_10 else 0.0,
            "semantic_similarity": float(np.mean(all_accuracies)) if all_accuracies else 0.0,
            "judge_accuracy": float(np.mean(all_is_correct)) if all_is_correct else 0.0,
            "citation_accuracy": float(np.mean(all_citations)) if all_citations else 0.0,
            "context_relevancy": float(np.mean(all_ctx_relevancy)) if all_ctx_relevancy else 0.0,
            "answer_relevancy": float(np.mean(all_ans_relevancy)) if all_ans_relevancy else 0.0,
        }
