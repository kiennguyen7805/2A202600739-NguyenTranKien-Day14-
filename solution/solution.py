"""
Day 14 — AI Evaluation & Benchmarking Pipeline
AICB-P1: AI Practical Competency Program, Phase 1

Instructions:
    1. Fill in every section marked with TODO.
    2. Do NOT change class/function signatures.
    3. Copy this file to solution/solution.py when done.
    4. Run: pytest tests/ -v
"""

from __future__ import annotations

import re
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# ---------------------------------------------------------------------------
# Task 1 — Data Models (Golden Dataset + Evaluation Results)
# ---------------------------------------------------------------------------

@dataclass
class QAPair:
    """
    A question-answer pair for evaluation (part of the Golden Dataset).
    """
    question: str
    expected_answer: str
    context: str = ""
    metadata: dict = field(default_factory=dict)
    retrieved_contexts: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """
    Evaluation result for a single Q&A pair.
    """
    qa_pair: QAPair
    actual_answer: str
    faithfulness: float
    relevance: float
    completeness: float
    passed: bool
    failure_type: str | None = None
    context_precision: float | None = None
    context_recall: float | None = None

    def overall_score(self) -> float:
        """Compute the average of faithfulness, relevance, and completeness."""
        return (self.faithfulness + self.relevance + self.completeness) / 3.0


# ---------------------------------------------------------------------------
# Task 2 — RAGAS Evaluator (Simplified word-overlap heuristic)
# ---------------------------------------------------------------------------

# Common English stopwords are ignored so overlap reflects *content* words,
# not filler (otherwise "is"/"a"/"the" inflate every score).
STOPWORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "as", "by", "and", "or",
    "it", "its", "this", "that", "these", "those", "from", "into", "than",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokenization, ignoring punctuation and stopwords."""
    if not text:
        return set()
    tokens = re.findall(r"\b\w+\b", text.lower())
    return {t for t in tokens if t not in STOPWORDS}


class RAGASEvaluator:
    """
    Evaluates RAG pipeline outputs using RAGAS-inspired heuristics.
    """

    def evaluate_faithfulness(self, answer: str, context: str) -> float:
        """
        Measure how grounded the answer is in the context.
        """
        if not answer:
            return 1.0
        ans_tokens = _tokenize(answer)
        ctx_tokens = _tokenize(context)
        if not ans_tokens:
            return 1.0
        val = len(ans_tokens & ctx_tokens) / len(ans_tokens)
        return max(0.0, min(1.0, val))

    def evaluate_relevance(self, answer: str, question: str) -> float:
        """
        Measure how relevant the answer is to the question.
        """
        if not question:
            return 1.0
        ans_tokens = _tokenize(answer)
        q_tokens = _tokenize(question)
        if not q_tokens:
            return 1.0
        val = len(ans_tokens & q_tokens) / len(q_tokens)
        return max(0.0, min(1.0, val))

    def evaluate_completeness(self, answer: str, expected: str) -> float:
        """
        Measure how well the answer covers the expected answer.
        """
        if not expected:
            return 1.0
        ans_tokens = _tokenize(answer)
        exp_tokens = _tokenize(expected)
        if not exp_tokens:
            return 1.0
        val = len(ans_tokens & exp_tokens) / len(exp_tokens)
        return max(0.0, min(1.0, val))

    # -----------------------------------------------------------------------
    # Task 2b — Retrieval-side metrics (evaluate the GET-CONTEXT step)
    # -----------------------------------------------------------------------

    def evaluate_context_recall(self, contexts: list[str], expected: str) -> float:
        """Context Recall — how much of the expected answer is covered by the
        UNION of retrieved chunks.
        """
        if not expected:
            return 1.0
        exp_tokens = _tokenize(expected)
        if not exp_tokens:
            return 1.0
        union_tokens = set()
        for chunk in contexts:
            union_tokens.update(_tokenize(chunk))
        val = len(exp_tokens & union_tokens) / len(exp_tokens)
        return max(0.0, min(1.0, val))

    def evaluate_context_precision(
        self,
        contexts: list[str],
        expected: str,
        relevance_threshold: float = 0.1,
    ) -> float:
        """Context Precision — RANK-AWARE Average Precision (AP@K).
        """
        if not expected:
            return 1.0
        E = _tokenize(expected)
        if not E:
            return 1.0
        if not contexts:
            return 0.0

        relevant_flags = []
        for chunk in contexts:
            C = _tokenize(chunk)
            overlap_ratio = len(C & E) / len(E) if E else 1.0
            relevant_flags.append(overlap_ratio >= relevance_threshold)

        num_relevant = sum(relevant_flags)
        if num_relevant == 0:
            return 0.0

        ap_sum = 0.0
        rel_count = 0
        for k_idx, is_rel in enumerate(relevant_flags):
            k = k_idx + 1
            if is_rel:
                rel_count += 1
                precision_at_k = rel_count / k
                ap_sum += precision_at_k

        return ap_sum / num_relevant

    def run_full_eval(
        self,
        answer: str,
        question: str,
        context: str,
        expected: str,
    ) -> EvalResult:
        """
        Run all three evaluations and combine into an EvalResult.
        """
        faithfulness = self.evaluate_faithfulness(answer, context)
        relevance = self.evaluate_relevance(answer, question)
        completeness = self.evaluate_completeness(answer, expected)

        passed = (faithfulness >= 0.5) and (relevance >= 0.5) and (completeness >= 0.5)

        failure_type = None
        if not passed:
            if faithfulness < 0.3:
                failure_type = "hallucination"
            elif relevance < 0.3:
                failure_type = "irrelevant"
            elif completeness < 0.3:
                failure_type = "incomplete"
            else:
                failure_type = "off_topic"

        qa_pair = QAPair(question=question, expected_answer=expected, context=context)

        return EvalResult(
            qa_pair=qa_pair,
            actual_answer=answer,
            faithfulness=faithfulness,
            relevance=relevance,
            completeness=completeness,
            passed=passed,
            failure_type=failure_type
        )


# ---------------------------------------------------------------------------
# Reranking helper
# ---------------------------------------------------------------------------

def rerank_by_overlap(contexts: list[str], query: str) -> list[str]:
    """A minimal lexical reranker: sort chunks by word overlap with the query."""
    return sorted(contexts, key=lambda c: len(_tokenize(c) & _tokenize(query)), reverse=True)


# ---------------------------------------------------------------------------
# Task 3 — LLM Judge
# ---------------------------------------------------------------------------

class LLMJudge:
    """
    Uses an LLM to score AI responses according to a rubric.
    """

    def __init__(self, judge_llm_fn: Callable[[str], str]) -> None:
        self.judge_llm_fn = judge_llm_fn

    def score_response(
        self,
        question: str,
        answer: str,
        rubric: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Score an AI response using the judge LLM.
        """
        prompt = f"Question: {question}\nAnswer: {answer}\nRubric: {rubric}"
        raw_response = self.judge_llm_fn(prompt)

        scores = {}
        try:
            match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            json_str = match.group(0) if match else raw_response
            parsed = json.loads(json_str)
            for k in rubric.keys():
                if k in parsed:
                    scores[k] = float(parsed[k])
                else:
                    scores[k] = 0.5
        except Exception:
            scores = {k: 0.5 for k in rubric.keys()}

        return {
            "scores": scores,
            "reasoning": raw_response
        }

    def detect_bias(self, scores_batch: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Detect potential bias patterns in a batch of judge scores.
        """
        all_scores = []
        for item in scores_batch:
            sc = item.get("scores", {})
            all_scores.extend(sc.values())
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.5

        positional_bias = False
        if len(scores_batch) > 1:
            first_item_scores = list(scores_batch[0].get("scores", {}).values())
            first_avg = sum(first_item_scores) / len(first_item_scores) if first_item_scores else 0.0

            rest_scores = []
            for item in scores_batch[1:]:
                rest_scores.extend(item.get("scores", {}).values())
            rest_avg = sum(rest_scores) / len(rest_scores) if rest_scores else 0.0

            positional_bias = first_avg > rest_avg + 0.15

        return {
            "positional_bias": positional_bias,
            "leniency_bias": avg_score > 0.8,
            "severity_bias": avg_score < 0.3
        }


# ---------------------------------------------------------------------------
# Task 4 — Benchmark Runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """
    Runs a full evaluation benchmark.
    """

    def run(
        self,
        qa_pairs: list[QAPair],
        agent_fn: Callable[[str], str],
        evaluator: RAGASEvaluator,
    ) -> list[EvalResult]:
        """
        Run all QA pairs through the agent and evaluate each result.
        """
        results = []
        for pair in qa_pairs:
            actual_answer = agent_fn(pair.question)
            eval_res = evaluator.run_full_eval(
                answer=actual_answer,
                question=pair.question,
                context=pair.context,
                expected=pair.expected_answer
            )
            eval_res.qa_pair = pair
            if pair.retrieved_contexts:
                eval_res.context_recall = evaluator.evaluate_context_recall(pair.retrieved_contexts, pair.expected_answer)
                eval_res.context_precision = evaluator.evaluate_context_precision(pair.retrieved_contexts, pair.expected_answer)
            results.append(eval_res)
        return results

    def generate_report(self, results: list[EvalResult]) -> dict[str, Any]:
        """
        Generate an aggregate report from evaluation results.
        """
        total = len(results)
        if total == 0:
            return {
                "total": 0,
                "passed": 0,
                "pass_rate": 0.0,
                "avg_faithfulness": 0.0,
                "avg_relevance": 0.0,
                "avg_completeness": 0.0,
                "failure_types": {}
            }

        passed = sum(1 for r in results if r.passed)
        avg_faithfulness = sum(r.faithfulness for r in results) / total
        avg_relevance = sum(r.relevance for r in results) / total
        avg_completeness = sum(r.completeness for r in results) / total

        failure_types = {}
        for r in results:
            if not r.passed and r.failure_type:
                failure_types[r.failure_type] = failure_types.get(r.failure_type, 0) + 1

        return {
            "total": total,
            "passed": passed,
            "pass_rate": passed / total,
            "avg_faithfulness": avg_faithfulness,
            "avg_relevance": avg_relevance,
            "avg_completeness": avg_completeness,
            "failure_types": failure_types
        }

    def run_regression(self, new_results: list[EvalResult], baseline_results: list[EvalResult]) -> dict:
        """Compare new evaluation results against a baseline."""
        total_new = len(new_results)
        total_base = len(baseline_results)

        new_faith = sum(r.faithfulness for r in new_results) / total_new if total_new else 0.0
        new_rel = sum(r.relevance for r in new_results) / total_new if total_new else 0.0
        new_comp = sum(r.completeness for r in new_results) / total_new if total_new else 0.0

        base_faith = sum(r.faithfulness for r in baseline_results) / total_base if total_base else 0.0
        base_rel = sum(r.relevance for r in baseline_results) / total_base if total_base else 0.0
        base_comp = sum(r.completeness for r in baseline_results) / total_base if total_base else 0.0

        regressions = []
        if base_faith - new_faith > 0.05:
            regressions.append("faithfulness")
        if base_rel - new_rel > 0.05:
            regressions.append("relevance")
        if base_comp - new_comp > 0.05:
            regressions.append("completeness")

        return {
            "new_avg_faithfulness": new_faith,
            "new_avg_relevance": new_rel,
            "new_avg_completeness": new_comp,
            "baseline_avg_faithfulness": base_faith,
            "baseline_avg_relevance": base_rel,
            "baseline_avg_completeness": base_comp,
            "regressions": regressions,
            "passed": len(regressions) == 0
        }

    def identify_failures(
        self,
        results: list[EvalResult],
        threshold: float = 0.5,
    ) -> list[EvalResult]:
        """
        Return EvalResults where any score is below threshold.
        """
        failures = []
        for r in results:
            if r.faithfulness < threshold or r.relevance < threshold or r.completeness < threshold:
                failures.append(r)
        return failures


# ---------------------------------------------------------------------------
# Task 5 — Failure Analyzer
# ---------------------------------------------------------------------------

class FailureAnalyzer:
    """
    Analyzes failed evaluation results to identify patterns and suggest fixes.
    """

    def categorize_failures(
        self, failures: list[EvalResult]
    ) -> dict[str, int]:
        """
        Count failures by failure_type.
        """
        categories = {}
        for f in failures:
            ft = f.failure_type or "unknown"
            categories[ft] = categories.get(ft, 0) + 1
        return categories

    def find_root_cause(self, failure: EvalResult) -> str:
        """
        Suggest a root cause for a single failure based on its scores.
        """
        f = failure.faithfulness
        r = failure.relevance
        c = failure.completeness

        min_val = min(f, r, c)
        counts = [f, r, c].count(min_val)
        if counts > 1:
            return "Multiple issues detected — review full pipeline"
        if min_val == f:
            return "Context is missing or irrelevant — improve retrieval"
        if min_val == r:
            return "Answer does not address the question — improve prompt clarity"
        return "Answer is missing key information — increase context window or improve generation"

    def generate_improvement_log(self, failures: list[EvalResult], suggestions: list[str]) -> str:
        """Generate a Markdown table logging failures and improvement actions."""
        log_lines = [
            "| Failure ID | Type | Root Cause | Suggested Fix | Status |",
            "|------------|------|------------|---------------|--------|"
        ]
        for i, f in enumerate(failures):
            fid = f"F{i+1:03d}"
            ftype = f.failure_type or "Unknown"
            cause = self.find_root_cause(f)
            fix = suggestions[i] if i < len(suggestions) else (suggestions[-1] if suggestions else "No suggestions available")
            log_lines.append(f"| {fid} | {ftype} | {cause} | {fix} | Open |")
        return "\n".join(log_lines)

    def generate_improvement_suggestions(
        self, failures: list[EvalResult]
    ) -> list[str]:
        """
        Generate a prioritized list of improvement suggestions based on failure patterns.
        """
        if not failures:
            return []

        categories = self.categorize_failures(failures)
        suggestions = []

        if categories.get("hallucination", 0) > 0:
            suggestions.append("Implement hallucination checker to filter unsupported claims")
            suggestions.append("Update system prompt to strictly enforce grounding in retrieved context")
        if categories.get("irrelevant", 0) > 0:
            suggestions.append("Refine system prompts and clarify prompt instructions to target user questions")
        if categories.get("incomplete", 0) > 0:
            suggestions.append("Increase chunk size in RAG pipeline to reduce context fragmentation")
            suggestions.append("Add few-shot examples showing complete answers to improve completeness")

        while len(suggestions) < 3:
            suggestions.append("Perform manual review of low-scoring queries to identify specific edge cases")
            suggestions.append("Optimize chunk overlap and chunking strategy for better search context")
            suggestions.append("Integrate a reranking model (e.g. cross-encoder) to improve context relevance")

        return suggestions[:max(3, len(suggestions))]
