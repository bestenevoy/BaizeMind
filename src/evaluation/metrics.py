import json
import re
import time
from typing import Any, Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from src.embeddings.bge_m3 import BGEM3Embedding
from src.llm.deepseek import get_reasoner_llm


class EvalMetrics:
    def __init__(self):
        self._embedding = BGEM3Embedding()
        self._judge_llm = None
        self._start_time = time.time()

    def _get_judge_llm(self):
        if self._judge_llm is None:
            self._judge_llm = get_reasoner_llm(temperature=0.0)
        return self._judge_llm

    # ═══════════ P1: Core Retrieval Metrics ═══════════

    def recall_at_k(self, retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> float:
        if not ground_truth_ids:
            return -1.0  # insufficient data marker
        retrieved = retrieved_ids[:k]
        matched = sum(1 for gt_id in ground_truth_ids if gt_id in retrieved)
        return matched / len(ground_truth_ids)

    def precision_at_k(self, retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> float:
        """Precision@k: ratio of retrieved chunks that are relevant (in ground_truth)."""
        if not ground_truth_ids:
            return -1.0
        retrieved = retrieved_ids[:k]
        if not retrieved:
            return 0.0
        matched = sum(1 for rid in retrieved if rid in ground_truth_ids)
        return matched / len(retrieved)

    def ndcg_at_k(self, retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> float:
        """NDCG@k: Normalized Discounted Cumulative Gain. Validates rerank quality."""
        if not ground_truth_ids:
            return -1.0
        retrieved = retrieved_ids[:k]
        # Binary relevance: 1 if in ground_truth, 0 otherwise
        dcg = 0.0
        for i, rid in enumerate(retrieved):
            rel = 1.0 if rid in ground_truth_ids else 0.0
            dcg += rel / np.log2(i + 2)  # i+2 because log2(1)=0

        # Ideal DCG: all ground_truth at top positions
        ideal_dcg = 0.0
        for i in range(min(k, len(ground_truth_ids))):
            ideal_dcg += 1.0 / np.log2(i + 2)

        return dcg / ideal_dcg if ideal_dcg > 0 else 0.0

    def mrr(self, retrieved_ids: list[str], ground_truth_ids: list[str]) -> float:
        """Mean Reciprocal Rank: 1 / rank of first relevant result."""
        if not ground_truth_ids:
            return -1.0
        for i, rid in enumerate(retrieved_ids):
            if rid in ground_truth_ids:
                return 1.0 / (i + 1)
        return 0.0

    # ═══════════ P1: Context & Answer Quality ═══════════

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
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"is_correct": False, "semantic_match": 0.0, "completeness": 0.0, "explanation": "Parse error"}

    def citation_accuracy(self, cited_sources: list[str], ground_truth_sources: list[str]) -> float:
        if not ground_truth_sources:
            return -1.0
        if not cited_sources:
            return 0.0
        matched = sum(1 for src in cited_sources if any(gt in src for gt in ground_truth_sources))
        return matched / max(len(cited_sources), 1)

    def context_relevancy(self, query: str, retrieved_texts: list[str]) -> float:
        if not retrieved_texts:
            return 0.0
        try:
            query_vec = self._embedding.encode_dense([query])[0]
            chunk_vecs = self._embedding.encode_dense(retrieved_texts)
            sims = cosine_similarity(query_vec.reshape(1, -1), chunk_vecs).flatten()
            return float(np.mean(sims))
        except Exception:
            return 0.0

    def answer_relevancy(self, query: str, answer: str) -> float:
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
            resp = llm.invoke(prompt)
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                return float(json.loads(match.group()).get("relevancy", 0))
        except Exception:
            pass
        return 0.0

    def faithfulness(self, answer: str, retrieved_texts: list[str]) -> float:
        if not answer or not retrieved_texts:
            return 0.0
        context = "\n---\n".join(t[:500] for t in retrieved_texts[:10])
        llm = self._get_judge_llm()
        prompt = (
            f"Rate whether the answer is fully grounded in the provided context. "
            f"A score of 1.0 means ALL claims in the answer are supported by the context. "
            f"A score of 0.0 means the answer is completely invented (hallucination).\n\n"
            f"Context:\n{context[:4000]}\n\n"
            f"Answer:\n{answer[:2000]}\n\n"
            f'Respond in JSON: {{"faithfulness": 0.0-1.0, "explanation": "..."}}'
        )
        try:
            resp = llm.invoke(prompt)
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                return float(json.loads(match.group()).get("faithfulness", 0))
        except Exception:
            pass
        return 0.0

    # ═══════════ P1: Hallucination Binary Split ═══════════

    def hallucination_split(self, answer: str, retrieved_texts: list[str]) -> dict[str, Any]:
        """
        Binary hallucination detection with intrinsic/extrinsic split.
        - intrinsic: hallucination where the model contradicts itself or the retrieved context
        - extrinsic: hallucination where the model invents facts not in context
        Returns {has_intrinsic: bool, has_extrinsic: bool, total_claims: int, hallucinated: int}
        """
        if not answer or not retrieved_texts:
            return {"has_intrinsic": False, "has_extrinsic": False, "intrinsic_count": 0, "extrinsic_count": 0, "total_claims": 0}
        context = "\n---\n".join(t[:500] for t in retrieved_texts[:10])
        llm = self._get_judge_llm()
        prompt = (
            f"Analyze the answer for hallucinations against the provided context. "
            f"Classify each unsupported claim:\n"
            f"- intrinsic_hallucination: answer says something that CONTRADICTS the context\n"
            f"- extrinsic_hallucination: answer says something NOT MENTIONED in the context (fabrication)\n\n"
            f"Context:\n{context[:4000]}\n\n"
            f"Answer:\n{answer[:2000]}\n\n"
            f'Respond in JSON: {{"intrinsic_count": int, "extrinsic_count": int, '
            f'"total_claims": int, "explanation": "..."}}'
        )
        try:
            resp = llm.invoke(prompt)
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                data = json.loads(match.group())
                return {
                    "has_intrinsic": data.get("intrinsic_count", 0) > 0,
                    "has_extrinsic": data.get("extrinsic_count", 0) > 0,
                    "intrinsic_count": data.get("intrinsic_count", 0),
                    "extrinsic_count": data.get("extrinsic_count", 0),
                    "total_claims": data.get("total_claims", 1),
                }
        except Exception:
            pass
        return {"has_intrinsic": False, "has_extrinsic": False, "intrinsic_count": 0, "extrinsic_count": 0, "total_claims": 0}

    def answer_completeness(self, predicted_answer: str, ground_truth_answer: str) -> float:
        """LLM-judged completeness: does the predicted answer cover all aspects of ground truth?"""
        if not predicted_answer or not ground_truth_answer:
            return 0.0
        llm = self._get_judge_llm()
        prompt = (
            f"Rate how completely the predicted answer covers all the information in the ground truth. "
            f"1.0 = fully covers all aspects. 0.0 = misses everything.\n\n"
            f"Ground Truth: {ground_truth_answer[:2000]}\n\n"
            f"Predicted: {predicted_answer[:2000]}\n\n"
            f'Respond in JSON: {{"completeness": 0.0-1.0, "explanation": "..."}}'
        )
        try:
            resp = llm.invoke(prompt)
            match = re.search(r"\{[\s\S]*\}", resp.content)
            if match:
                return float(json.loads(match.group()).get("completeness", 0))
        except Exception:
            pass
        return 0.0

    # ═══════════ P2: Advanced Metrics ═══════════

    def correct_refusal_rate(self, results: list[dict]) -> float:
        """Rate of correctly refusing to answer when no context is sufficient."""
        refusals = 0
        total = 0
        for r in results:
            if r.get("is_negative_sample", False):
                total += 1
                answer = r.get("predicted_answer", "").lower()
                if any(phrase in answer for phrase in ["no information", "not provided", "not found",
                                                         "cannot answer", "没有足够", "无法回答",
                                                         "无依据", "information provided"]):
                    refusals += 1
        return refusals / total if total > 0 else -1.0

    def context_redundancy(self, retrieved_texts: list[str]) -> float:
        """Measure how redundant/duplicated the retrieved context is.
        Returns ratio of near-duplicate chunks."""
        if len(retrieved_texts) <= 1:
            return 0.0
        try:
            if len(retrieved_texts) > 1:
                vecs = self._embedding.encode_dense(retrieved_texts)
                sim_matrix = cosine_similarity(vecs, vecs)
                # Upper triangle, exclude diagonal
                n = len(retrieved_texts)
                if n > 1:
                    upper = sim_matrix[np.triu_indices(n, k=1)]
                    redundant = np.sum(upper > 0.8)  # threshold for near-duplicate
                    max_pairs = n * (n - 1) / 2
                    return float(redundant / max_pairs) if max_pairs > 0 else 0.0
        except Exception:
            pass
        return 0.0

    def delta_ndcg(self, pre_rerank_ids: list[str], post_rerank_ids: list[str], ground_truth_ids: list[str], k: int = 5) -> float:
        """NDCG improvement from reranking: post_ndcg - pre_ndcg."""
        if not ground_truth_ids:
            return 0.0
        pre = self.ndcg_at_k(pre_rerank_ids, ground_truth_ids, k)
        post = self.ndcg_at_k(post_rerank_ids, ground_truth_ids, k)
        if pre < 0 or post < 0:
            return 0.0
        return post - pre

    def filter_drop_rate(self, pre_count: int, post_count: int) -> float:
        """Rate of chunks dropped by threshold filtering. 0 = none dropped, 1 = all dropped."""
        return 1.0 - (post_count / pre_count) if pre_count > 0 else 0.0

    # ═══════════ P3: Performance Metrics ═══════════

    def timing_stats(self, processing_times_ms: list[float]) -> dict:
        if not processing_times_ms:
            return {"mean_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0}
        arr = np.array(processing_times_ms)
        return {
            "mean_ms": float(np.mean(arr)),
            "p50_ms": float(np.percentile(arr, 50)),
            "p95_ms": float(np.percentile(arr, 95)),
            "p99_ms": float(np.percentile(arr, 99)),
        }

    # ═══════════ Aggregation ═══════════

    def compute_metrics(
        self,
        samples: list[dict],
        results: list[dict],
    ) -> dict[str, Any]:
        """Compute all evaluation metrics. Returns dict with metric groups."""
        # Collectors
        p_recall_5, p_recall_10 = [], []
        p_precision_5, p_precision_10 = [], []
        p_ndcg_5, p_delta_ndcg = [], []
        p_mrr = []
        p_ctx_relevancy, p_ans_relevancy, p_faithfulness = [], [], []
        p_completeness = []
        p_citations = []
        p_is_correct, p_semantic_sim = [], []
        p_ctx_redundancy = []
        p_filter_drops = []
        p_timings = []
        p_intrinsic_has, p_extrinsic_has = 0, 0
        p_intrinsic_cnt, p_extrinsic_cnt, p_total_claims = 0, 0, 0

        for sample, result in zip(samples, results):
            # ── Retrieval metrics ──
            gt_ids = sample.get("ground_truth_ids", [])
            retrieved_ids = result.get("retrieved_ids", [])
            retrieved_texts = result.get("retrieved_texts", [])
            predicted = result.get("predicted_answer", "")
            is_error = "error" in predicted.lower() or predicted.startswith("ERROR")

            if gt_ids:
                p_recall_5.append(self.recall_at_k(retrieved_ids, gt_ids, 5))
                p_recall_10.append(self.recall_at_k(retrieved_ids, gt_ids, 10))
                p_precision_5.append(self.precision_at_k(retrieved_ids, gt_ids, 5))
                p_precision_10.append(self.precision_at_k(retrieved_ids, gt_ids, 10))
                p_ndcg_5.append(self.ndcg_at_k(retrieved_ids, gt_ids, 5))
                p_mrr.append(self.mrr(retrieved_ids, gt_ids))

                # Delta NDCG (rerank gain)
                pre_rerank_ids = result.get("pre_rerank_ids", [])
                if pre_rerank_ids:
                    p_delta_ndcg.append(self.delta_ndcg(pre_rerank_ids, retrieved_ids, gt_ids, 5))

            # Filter drop rate
            pre_count = result.get("pre_filter_chunk_count", 0)
            post_count = result.get("post_filter_chunk_count", len(retrieved_ids))
            if pre_count > 0:
                p_filter_drops.append(self.filter_drop_rate(pre_count, post_count))

            # ── Context quality ──
            if retrieved_texts:
                p_ctx_relevancy.append(self.context_relevancy(sample["query"], retrieved_texts))
                p_ctx_redundancy.append(self.context_redundancy(retrieved_texts))

            # ── Answer quality ──
            if predicted and not is_error:
                p_ans_relevancy.append(self.answer_relevancy(sample["query"], predicted))
                p_faithfulness.append(self.faithfulness(predicted, retrieved_texts))
                p_completeness.append(self.answer_completeness(predicted, sample.get("ground_truth_answer", "")))

            # ── Hallucination split ──
            if predicted and retrieved_texts and not is_error:
                hall = self.hallucination_split(predicted, retrieved_texts)
                if hall["has_intrinsic"]:
                    p_intrinsic_has += 1
                if hall["has_extrinsic"]:
                    p_extrinsic_has += 1
                p_intrinsic_cnt += hall["intrinsic_count"]
                p_extrinsic_cnt += hall["extrinsic_count"]
                p_total_claims += hall["total_claims"]

            # ── Judge accuracy ──
            judge = self.judge_accuracy(predicted, sample.get("ground_truth_answer", ""))
            sim = self.answer_accuracy(predicted, sample.get("ground_truth_answer", ""))
            p_semantic_sim.append(sim)
            p_is_correct.append(1.0 if judge.get("is_correct") else 0.0)
            p_completeness.append(judge.get("completeness", 0.0))

            cit = self.citation_accuracy(result.get("cited_sources", []), sample.get("ground_truth_sources", []))
            p_citations.append(cit)

            # ── Timing ──
            t = result.get("processing_time_ms", 0)
            if t > 0:
                p_timings.append(t)

        n = len(samples)

        def _mean(lst, default=0.0):
            valid = [v for v in lst if v >= 0]
            return float(np.mean(valid)) if valid else default

        def _mean_or_none(lst):
            valid = [v for v in lst if v >= 0]
            return float(np.mean(valid)) if valid else None

        timing = self.timing_stats(p_timings)
        elapsed = time.time() - self._start_time

        return {
            "num_samples": n,
            # ═══ P1: Core ═══
            "context_relevancy": _mean(p_ctx_relevancy),
            "context_recall": _mean(p_recall_10),
            "answer_relevancy": _mean(p_ans_relevancy),
            "faithfulness": _mean(p_faithfulness),
            # ═══ P1: Precision & NDCG ═══
            "precision_at_5": _mean_or_none(p_precision_5),
            "precision_at_10": _mean_or_none(p_precision_10),
            "ndcg_at_5": _mean_or_none(p_ndcg_5),
            # ═══ P1: Hallucination ═══
            "intrinsic_hallucination_rate": (p_intrinsic_has / n) if n > 0 and p_total_claims > 0 else 0.0,
            "extrinsic_hallucination_rate": (p_extrinsic_has / n) if n > 0 and p_total_claims > 0 else 0.0,
            "intrinsic_hallucination_score": (p_intrinsic_cnt / p_total_claims) if p_total_claims > 0 else 0.0,
            "extrinsic_hallucination_score": (p_extrinsic_cnt / p_total_claims) if p_total_claims > 0 else 0.0,
            # ═══ P1: Completeness ═══
            "answer_completeness": _mean(p_completeness),
            # ═══ P2 ═══
            "correct_refusal_rate": _mean_or_none([self.correct_refusal_rate(results)]),
            "mrr": _mean_or_none(p_mrr),
            "context_redundancy": _mean(p_ctx_redundancy),
            "delta_ndcg": _mean_or_none(p_delta_ndcg),
            "filter_drop_rate": _mean(p_filter_drops),
            # ═══ P3 ═══
            "timing_mean_ms": timing["mean_ms"],
            "timing_p50_ms": timing["p50_ms"],
            "timing_p95_ms": timing["p95_ms"],
            "timing_p99_ms": timing["p99_ms"],
            "eval_total_time_s": elapsed,
            # ═══ Legacy ═══
            "recall_at_5": _mean(p_recall_5),
            "recall_at_10": _mean(p_recall_10),
            "semantic_similarity": _mean(p_semantic_sim),
            "judge_accuracy": _mean(p_is_correct),
            "citation_accuracy": _mean(p_citations),
        }
