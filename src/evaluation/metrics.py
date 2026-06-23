"""Evaluation metrics — ragas for QA quality + custom IR/hallucination/timing metrics."""
import time
import json
import re
from typing import Any, Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from datasets import Dataset

from src.embeddings.bge_m3 import BGEM3Embedding
from src.llm.deepseek import get_reasoner_llm
from config.settings import settings


def _ragas_vertexai_patch():
    """Shim: ragas 0.4.x tries to import ChatVertexAI from old langchain_community path."""
    import langchain_community.chat_models
    if not hasattr(langchain_community.chat_models, "vertexai"):
        langchain_community.chat_models.vertexai = __import__("types").SimpleNamespace()
        from langchain_google_vertexai.chat_models import ChatVertexAI
        langchain_community.chat_models.vertexai.ChatVertexAI = ChatVertexAI


class EvalMetrics:
    """Handles custom metrics not covered by ragas (IR, hallucination split, timing)."""

    def __init__(self):
        self._embedding = BGEM3Embedding()
        self._judge_llm = None
        self._start_time = time.time()

    def _get_judge_llm(self):
        if self._judge_llm is None:
            self._judge_llm = get_reasoner_llm(temperature=0.0)
        return self._judge_llm

    # ═══════════ Core IR Metrics ═══════════

    def recall_at_k(self, retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> float:
        if not ground_truth_ids:
            return -1.0
        retrieved = retrieved_ids[:k]
        matched = sum(1 for gt_id in ground_truth_ids if gt_id in retrieved)
        return matched / len(ground_truth_ids)

    def precision_at_k(self, retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> float:
        if not ground_truth_ids:
            return -1.0
        retrieved = retrieved_ids[:k]
        if not retrieved:
            return 0.0
        matched = sum(1 for rid in retrieved if rid in ground_truth_ids)
        return matched / len(retrieved)

    def ndcg_at_k(self, retrieved_ids: list[str], ground_truth_ids: list[str], k: int) -> float:
        if not ground_truth_ids:
            return -1.0
        retrieved = retrieved_ids[:k]
        dcg = 0.0
        for i, rid in enumerate(retrieved):
            rel = 1.0 if rid in ground_truth_ids else 0.0
            dcg += rel / np.log2(i + 2)
        ideal_dcg = sum(1.0 / np.log2(i + 2) for i in range(min(k, len(ground_truth_ids))))
        return dcg / ideal_dcg if ideal_dcg > 0 else 0.0

    def mrr(self, retrieved_ids: list[str], ground_truth_ids: list[str]) -> float:
        if not ground_truth_ids:
            return -1.0
        for i, rid in enumerate(retrieved_ids):
            if rid in ground_truth_ids:
                return 1.0 / (i + 1)
        return 0.0

    # ═══════════ Citation ═══════════

    def citation_accuracy(self, cited_sources: list[str], ground_truth_sources: list[str]) -> float:
        if not ground_truth_sources:
            return -1.0
        if not cited_sources:
            return 0.0
        matched = sum(1 for src in cited_sources if any(gt in src for gt in ground_truth_sources))
        return matched / max(len(cited_sources), 1)

    # ═══════════ Hallucination Split ═══════════

    def hallucination_split(self, answer: str, retrieved_texts: list[str]) -> dict[str, Any]:
        if not answer or not retrieved_texts:
            return {"has_intrinsic": False, "has_extrinsic": False, "intrinsic_count": 0, "extrinsic_count": 0, "total_claims": 0}
        context = "\n---\n".join(t[:500] for t in retrieved_texts[:10])
        llm = self._get_judge_llm()
        prompt = (
            f"Analyze the answer for hallucinations against the provided context. "
            f"Classify each unsupported claim:\n"
            f"- intrinsic_hallucination: answer CONTRADICTS the context\n"
            f"- extrinsic_hallucination: answer says something NOT MENTIONED in context (fabrication)\n\n"
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

    # ═══════════ P2 Advanced Metrics ═══════════

    def correct_refusal_rate(self, results: list[dict]) -> float:
        refusals, total = 0, 0
        for r in results:
            if r.get("is_negative_sample", False):
                total += 1
                answer = r.get("predicted_answer", "").lower()
                if any(phrase in answer for phrase in [
                    "no information", "not provided", "not found", "cannot answer",
                    "没有足够", "无法回答", "无依据", "information provided",
                ]):
                    refusals += 1
        return refusals / total if total > 0 else -1.0

    def context_redundancy(self, retrieved_texts: list[str]) -> float:
        if len(retrieved_texts) <= 1:
            return 0.0
        try:
            vecs = self._embedding.encode_dense(retrieved_texts)
            sim_matrix = cosine_similarity(vecs, vecs)
            n = len(retrieved_texts)
            upper = sim_matrix[np.triu_indices(n, k=1)]
            redundant = np.sum(upper > 0.8)
            max_pairs = n * (n - 1) / 2
            return float(redundant / max_pairs) if max_pairs > 0 else 0.0
        except Exception:
            return 0.0

    def delta_ndcg(self, pre_rerank_ids: list[str], post_rerank_ids: list[str], ground_truth_ids: list[str], k: int = 5) -> float:
        if not ground_truth_ids:
            return 0.0
        pre = self.ndcg_at_k(pre_rerank_ids, ground_truth_ids, k)
        post = self.ndcg_at_k(post_rerank_ids, ground_truth_ids, k)
        if pre < 0 or post < 0:
            return 0.0
        return post - pre

    def filter_drop_rate(self, pre_count: int, post_count: int) -> float:
        return 1.0 - (post_count / pre_count) if pre_count > 0 else 0.0

    # ═══════════ P3 Performance ═══════════

    @staticmethod
    def timing_stats(processing_times_ms: list[float]) -> dict:
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

    def compute_metrics(self, samples: list[dict], results: list[dict]) -> dict[str, Any]:
        """Compute custom metrics (IR, hallucination, timing) — ragas handles QA quality separately."""
        p_recall_5, p_recall_10 = [], []
        p_precision_5, p_precision_10 = [], []
        p_ndcg_5, p_delta_ndcg = [], []
        p_mrr = []
        p_citations = []
        p_ctx_redundancy = []
        p_filter_drops = []
        p_timings = []
        p_intrinsic_has, p_extrinsic_has = 0, 0
        p_intrinsic_cnt, p_extrinsic_cnt, p_total_claims = 0, 0, 0

        for sample, result in zip(samples, results):
            gt_ids = sample.get("ground_truth_ids", [])
            retrieved_ids = result.get("retrieved_ids", [])
            retrieved_texts = result.get("retrieved_texts", [])
            predicted = result.get("predicted_answer", "")
            is_error = "error" in predicted.lower() or predicted.startswith("ERROR")

            # IR metrics
            if gt_ids:
                p_recall_5.append(self.recall_at_k(retrieved_ids, gt_ids, 5))
                p_recall_10.append(self.recall_at_k(retrieved_ids, gt_ids, 10))
                p_precision_5.append(self.precision_at_k(retrieved_ids, gt_ids, 5))
                p_precision_10.append(self.precision_at_k(retrieved_ids, gt_ids, 10))
                p_ndcg_5.append(self.ndcg_at_k(retrieved_ids, gt_ids, 5))
                p_mrr.append(self.mrr(retrieved_ids, gt_ids))
                pre_rerank_ids = result.get("pre_rerank_ids", [])
                if pre_rerank_ids:
                    p_delta_ndcg.append(self.delta_ndcg(pre_rerank_ids, retrieved_ids, gt_ids, 5))

            # Filter drop rate
            pre_count = result.get("pre_filter_chunk_count", 0)
            post_count = result.get("post_filter_chunk_count", len(retrieved_ids))
            if pre_count > 0:
                p_filter_drops.append(self.filter_drop_rate(pre_count, post_count))

            # Context redundancy
            if retrieved_texts:
                p_ctx_redundancy.append(self.context_redundancy(retrieved_texts))

            # Hallucination split
            if predicted and retrieved_texts and not is_error:
                hall = self.hallucination_split(predicted, retrieved_texts)
                if hall["has_intrinsic"]:
                    p_intrinsic_has += 1
                if hall["has_extrinsic"]:
                    p_extrinsic_has += 1
                p_intrinsic_cnt += hall["intrinsic_count"]
                p_extrinsic_cnt += hall["extrinsic_count"]
                p_total_claims += hall["total_claims"]

            # Citation accuracy
            cit = self.citation_accuracy(result.get("cited_sources", []), sample.get("ground_truth_sources", []))
            p_citations.append(cit)

            # Timing
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
            # P1: Retrieval
            "recall_at_5": _mean(p_recall_5),
            "recall_at_10": _mean(p_recall_10),
            "precision_at_5": _mean_or_none(p_precision_5),
            "precision_at_10": _mean_or_none(p_precision_10),
            "ndcg_at_5": _mean_or_none(p_ndcg_5),
            "mrr": _mean_or_none(p_mrr),
            # P1: Hallucination
            "intrinsic_hallucination_rate": (p_intrinsic_has / n) if n > 0 and p_total_claims > 0 else 0.0,
            "extrinsic_hallucination_rate": (p_extrinsic_has / n) if n > 0 and p_total_claims > 0 else 0.0,
            "intrinsic_hallucination_score": (p_intrinsic_cnt / p_total_claims) if p_total_claims > 0 else 0.0,
            "extrinsic_hallucination_score": (p_extrinsic_cnt / p_total_claims) if p_total_claims > 0 else 0.0,
            # P1: Citation
            "citation_accuracy": _mean(p_citations),
            # P2
            "correct_refusal_rate": _mean_or_none([self.correct_refusal_rate(results)]),
            "context_redundancy": _mean(p_ctx_redundancy),
            "delta_ndcg": _mean_or_none(p_delta_ndcg),
            "filter_drop_rate": _mean(p_filter_drops),
            # P3
            "timing_mean_ms": timing["mean_ms"],
            "timing_p50_ms": timing["p50_ms"],
            "timing_p95_ms": timing["p95_ms"],
            "timing_p99_ms": timing["p99_ms"],
            "eval_total_time_s": elapsed,
        }


# ═══════════ Ragas QA-quality metrics ═══════════

def compute_ragas_metrics(
    samples: list[dict],
    results: list[dict],
) -> dict[str, Any]:
    """Compute QA-quality metrics via ragas (faithfulness, answer_relevancy,
    context_precision, context_recall, answer_correctness).

    Requires: question, answer, contexts (list[str]), ground_truth per sample.
    """
    _ragas_vertexai_patch()

    from ragas import evaluate
    from ragas.metrics.collections import (
        Faithfulness,
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        AnswerCorrectness,
    )
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    # Build LLM wrappers for DeepSeek + SiliconFlow
    evaluator_llm = LangchainLLMWrapper(ChatOpenAI(
        model=settings.deepseek_chat_model,
        openai_api_key=settings.deepseek_api_key,
        openai_api_base=settings.deepseek_base_url,
        temperature=0,
    ))
    evaluator_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
        model=settings.siliconflow_embedding_model,
        openai_api_key=settings.siliconflow_api_key,
        openai_api_base="https://api.siliconflow.cn/v1",
    ))

    # Build ragas Dataset rows
    rows = []
    for sample, result in zip(samples, results):
        predicted = result.get("predicted_answer", "")
        if not predicted or predicted.startswith("ERROR"):
            continue
        rows.append({
            "user_input": sample["query"],
            "response": predicted,
            "retrieved_contexts": result.get("retrieved_texts", []),
            "reference": sample.get("ground_truth_answer", ""),
        })

    if not rows:
        return {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
            "answer_correctness": 0.0,
        }

    dataset = Dataset.from_list(rows)

    metrics = [
        Faithfulness(llm=evaluator_llm),
        AnswerRelevancy(llm=evaluator_llm, embeddings=evaluator_embeddings),
        ContextPrecision(llm=evaluator_llm),
        ContextRecall(llm=evaluator_llm),
        AnswerCorrectness(llm=evaluator_llm, embeddings=evaluator_embeddings),
    ]

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        show_progress=False,
    )

    # result is a dict-like EvaluationResult
    scores = {k: float(v) for k, v in result.items() if not k.startswith("_")}
    return {
        "faithfulness": scores.get("faithfulness", 0.0),
        "answer_relevancy": scores.get("answer_relevancy", 0.0),
        "context_precision": scores.get("context_precision", 0.0),
        "context_recall": scores.get("context_recall", 0.0),
        "answer_correctness": scores.get("answer_correctness", 0.0),
    }
