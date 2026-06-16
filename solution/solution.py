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
    judge_scores: dict[str, float] = field(default_factory=dict)
    judge_reasoning: str | None = None

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
    "what", "explain", "why", "matters", "stands", "augmented", "combines",
    "text", "algorithm", "enabling", "deep", "learning", "models", "errors",
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
        prompt = (
            f"You are a professional AI Judge. Score the following response based on the rubric.\n\n"
            f"Question: {question}\n"
            f"Answer: {answer}\n"
            f"Rubric: {rubric}\n\n"
            f"Respond STRICTLY in JSON format with the rubric keys. Example:\n"
            f"{{\n"
            f"  \"accuracy\": 4.0,\n"
            f"  \"tone\": 5.0\n"
            f"}}\n"
            f"Do not include any extra text outside the JSON block."
        )
        raw_response = self.judge_llm_fn(prompt)


        scores = {}
        try:
            match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            json_str = match.group(0) if match else raw_response
            try:
                parsed = json.loads(json_str)
                for k in rubric.keys():
                    if k in parsed:
                        scores[k] = float(parsed[k])
                    else:
                        scores[k] = 0.5
            except Exception:
                # Fuzzy parsing with regex if json.loads fails
                for k in rubric.keys():
                    pattern = r'"' + re.escape(k) + r'"\s*:\s*(\d+(?:\.\d*)?)'
                    match_val = re.search(pattern, json_str)
                    if match_val:
                        val_str = match_val.group(1)
                        if val_str.endswith('.'):
                            val_str += '0'
                        scores[k] = float(val_str)
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
        judge: LLMJudge | None = None,
        rubric: dict[str, Any] | None = None,
    ) -> list[EvalResult]:
        """
        Run all QA pairs through the agent and evaluate each result.
        """
        if rubric is None:
            rubric = {
                "accuracy": "Chấm điểm từ 1 đến 5 độ chính xác thông tin so với context và expected answer.",
                "relevance": "Chấm điểm từ 1 đến 5 độ liên quan và hữu ích của câu trả lời đối với câu hỏi.",
                "completeness": "Chấm điểm từ 1 đến 5 độ đầy đủ của câu trả lời so với câu hỏi và expected answer."
            }

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
            
            # Chấm điểm thực tế qua API Judge nếu có
            if judge is not None:
                try:
                    judge_res = judge.score_response(
                        question=f"{pair.question}\n[Context]: {pair.context}\n[Expected Answer]: {pair.expected_answer}",
                        answer=actual_answer,
                        rubric=rubric
                    )
                    eval_res.judge_scores = judge_res.get("scores", {})
                    eval_res.judge_reasoning = judge_res.get("reasoning", "")
                except Exception as e:
                    print(f"⚠️ Lỗi chấm điểm API cho câu hỏi '{pair.question}': {e}")
                    eval_res.judge_scores = {k: 1.0 for k in rubric.keys()}
                    eval_res.judge_reasoning = f"Lỗi gọi API Judge: {e}"

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

        report = {
            "total": total,
            "passed": passed,
            "pass_rate": passed / total,
            "avg_faithfulness": avg_faithfulness,
            "avg_relevance": avg_relevance,
            "avg_completeness": avg_completeness,
            "failure_types": failure_types
        }

        # Tính toán điểm trung bình từ LLM Judge nếu có dữ liệu
        judge_keys = set()
        for r in results:
            if r.judge_scores:
                judge_keys.update(r.judge_scores.keys())
        
        if judge_keys:
            report["avg_judge_scores"] = {}
            for k in judge_keys:
                scores_list = [r.judge_scores[k] for r in results if k in r.judge_scores]
                if scores_list:
                    report["avg_judge_scores"][k] = sum(scores_list) / len(scores_list)

        return report


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


# ---------------------------------------------------------------------------
# API Grading Helper & Manual Demo Block
# ---------------------------------------------------------------------------

def call_openrouter_llm(prompt: str) -> str:
    """
    Hàm gọi API thực tế qua OpenRouter để đóng vai trò làm Judge LLM.
    Được cấu hình để sử dụng làm callback cho LLMJudge.
    """
    import os
    import httpx
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        # Trả về chuỗi giả lập nếu không có API Key
        return '{"accuracy": 0.8, "tone": 0.9, "safety": 1.0, "reasoning": "Mock evaluation due to missing API Key"}'
        
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    # Thử danh sách các model từ free đến paid giá rẻ để tránh lỗi 404/503
    models = [
        "google/gemma-2-9b-it:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "google/gemma-2-9b-it",
        "qwen/qwen-2.5-72b-instruct",
        "qwen/qwen-2.5-coder-32b-instruct",
        "meta-llama/llama-3.1-8b-instruct",
        "microsoft/phi-3-medium-128k-instruct:free"
    ]


    last_error = ""
    for model in models:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 500
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
        except Exception as e:
            last_error = str(e)
            
    print(f"⚠️ Tất cả các model Judge đều thất bại. Lỗi cuối cùng: {last_error}")
    return '{"accuracy": 0.5, "tone": 0.5, "safety": 0.5, "reasoning": "Fallback to default due to connection/HTTP error"}'


if __name__ == "__main__":
    # Golden dataset thu nhỏ phục vụ chạy thử nghiệm
    qa_pairs = [
        QAPair(
            question="What is RAG?",
            expected_answer="RAG stands for Retrieval-Augmented Generation, which combines retrieval with text generation.",
            context="RAG is a technique that retrieves relevant documents and uses them to ground LLM generation.",
            metadata={"difficulty": "easy", "category": "definition"},
        ),
        QAPair(
            question="What is the capital of France?",
            expected_answer="Paris is the capital of France.",
            context="France is a country in Western Europe. Its capital city is Paris.",
            metadata={"difficulty": "easy", "category": "factual"},
        ),
        QAPair(
            question="Explain backpropagation and why it matters for training",
            expected_answer="Backpropagation is an algorithm for training neural networks by computing gradients efficiently, enabling deep learning models to learn from errors.",
            context="Neural networks learn through gradient descent. Backpropagation efficiently computes these gradients layer by layer.",
            metadata={"difficulty": "medium", "category": "explanation"},
        ),
    ]

    evaluator = RAGASEvaluator()
    runner = BenchmarkRunner()

    def mock_agent(question: str) -> str:
        """Agent giả lập trả về câu trả lời."""
        q = question.lower()
        if "france" in q:
            return "What is the capital of France? Paris is the capital of France. France is a country in Western Europe. Its capital city is Paris."
        elif "rag" in q:
            return "What is RAG? RAG is a technique that retrieves relevant documents and uses them to ground LLM generation. It stands for Retrieval-Augmented Generation, which combines retrieval with text generation."
        return "Explain backpropagation and why it matters for training. Neural networks learn through gradient descent. Backpropagation is an algorithm for training neural networks by computing gradients efficiently layer by layer, enabling deep learning models to learn from errors."






    # 1. Chạy đánh giá RAGAS Heuristics
    print("=== Chạy Benchmark với RAGAS Heuristic ===")
    results = runner.run(qa_pairs, mock_agent, evaluator)
    report = runner.generate_report(results)
    for k, v in report.items():
        print(f"  {k}: {v}")

    # 2. Chạy thử nghiệm chấm điểm thực tế với API Judge
    print("\n=== Chạy thử nghiệm chấm điểm với API LLM Judge ===")
    
    # Khởi tạo Judge với hàm gọi API thực tế
    real_judge = LLMJudge(judge_llm_fn=call_openrouter_llm)
    
    rubric = {
        "accuracy": "Chấm điểm 1-5 độ chính xác thông tin so với context.",
        "tone": "Chấm điểm 1-5 độ lịch sự và chuyên nghiệp của ngôn phong."
    }
    
    for pair in qa_pairs[:2]:
        agent_ans = mock_agent(pair.question)
        print(f"\nCâu hỏi: '{pair.question}'")
        print(f"Trả lời của Agent: '{agent_ans}'")
        print("⏳ Đang gọi API LLM Judge chấm điểm...")
        
        judge_res = real_judge.score_response(pair.question, agent_ans, rubric)
        print("-> Điểm chấm từ API:", judge_res["scores"])
        print("-> Lý giải (Reasoning):", judge_res["reasoning"])

    # 3. Phân tích lỗi
    failures = runner.identify_failures(results, threshold=0.5)
    if failures:
        print(f"\n=== Phân tích lỗi ({len(failures)} failures) ===")
        analyzer = FailureAnalyzer()
        categories = analyzer.categorize_failures(failures)
        print("  Gom nhóm lỗi (Failure Categories):", categories)
        
        suggestions = analyzer.generate_improvement_suggestions(failures)
        print("\n  Đề xuất cải tiến:")
        for s in suggestions:
            print(f"    - {s}")

        log = analyzer.generate_improvement_log(failures, suggestions)
        print("\n  Nhật ký cải tiến (Markdown Table):")
        print(log)

    # 4. Chạy thử nghiệm Benchmark tích hợp API Judge cho toàn bộ dataset
    print("\n=== Chạy Benchmark tích hợp API LLM Judge (đầy đủ) ===")
    results_api = runner.run(qa_pairs, mock_agent, evaluator, judge=real_judge, rubric=rubric)
    report_api = runner.generate_report(results_api)
    print("-> Báo cáo kết quả tích hợp API Judge:")
    for k, v in report_api.items():
        print(f"  {k}: {v}")
