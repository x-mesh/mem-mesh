"""LongMemEval benchmark runner for mem-mesh.

Usage:
    # Full 500-question run
    python benchmarks/longmemeval/run_benchmark.py --variant s --topk 5 --cot

    # Quick test (10 questions)
    python benchmarks/longmemeval/run_benchmark.py --variant s --max-questions 10

    # Resume interrupted run
    python benchmarks/longmemeval/run_benchmark.py --resume

    # Report only from existing results
    python benchmarks/longmemeval/run_benchmark.py --report-only
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Log file for progress (claude subprocess can interfere with stdout)
_LOG_FILE: "open | None" = None


def _log(msg: str, end: str = "\n") -> None:
    """Write to both stdout and log file."""
    try:
        sys.stdout.write(msg + end)
        sys.stdout.flush()
    except Exception:
        pass
    if _LOG_FILE:
        _LOG_FILE.write(msg + end)
        _LOG_FILE.flush()

from benchmarks.longmemeval.checkpoint import (
    CheckpointData,
    QuestionResult,
    add_result,
    get_failed_question_ids,
    load_checkpoint,
    save_checkpoint,
    update_result,
)
from benchmarks.longmemeval.config import BenchmarkConfig
from benchmarks.longmemeval.dataset import LongMemEvalQuestion, download_dataset, load_questions
from benchmarks.longmemeval.evaluator import evaluate_answer
from benchmarks.longmemeval.generator import generate_answer
from benchmarks.longmemeval.indexer import index_question
from benchmarks.longmemeval.report import generate_report, save_report
from benchmarks.longmemeval.retriever import retrieve_for_question

logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
_shutdown_requested = False

QUESTION_TYPES = [
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
]


def _log_report(report: dict) -> None:
    """Log report summary."""
    if not report:
        _log("No results available.")
        return
    s = report["summary"]
    _log("\n" + "=" * 60)
    _log("  LongMemEval Benchmark Report")
    _log("=" * 60)
    _log(f"\n  Total Questions:         {s['total_questions']}")
    _log(f"  Overall Accuracy:        {s['overall_accuracy']:.1%}")
    _log(f"  Task-Averaged Accuracy:  {s['task_averaged_accuracy']:.1%}")
    if s.get("abstention_count"):
        _log(f"  Abstention Accuracy:     {s['abstention_accuracy']:.1%} ({s['abstention_count']} questions)")
    _log("\n  --- Per-Category Accuracy ---")
    for qtype, data in report.get("by_category", {}).items():
        _log(
            f"  {qtype:30s}  {data['accuracy']:6.1%}  "
            f"({data['correct']}/{data['count']})  "
            f"recall_any={data['recall_any']:.2f}  recall_all={data['recall_all']:.2f}"
        )
    rm = report.get("retrieval_metrics", {})
    _log(f"\n  --- Retrieval Metrics ---")
    _log(f"  Recall@K (any):  {rm.get('recall_any_avg', 0):.4f}")
    _log(f"  Recall@K (all):  {rm.get('recall_all_avg', 0):.4f}")
    t = report.get("timing", {})
    _log(f"\n  --- Timing ---")
    _log(f"  Avg search:      {t.get('avg_search_ms', 0):.0f} ms")
    _log(f"  Avg generation:  {t.get('avg_generation_s', 0):.1f} s")
    c = report.get("config", {})
    _log(f"\n  --- Config ---")
    _log(
        f"  variant={c.get('variant')}  topk={c.get('topk')}  "
        f"mode={c.get('search_mode')}  cot={c.get('use_cot')}  "
        f"model={c.get('claude_model')}"
    )
    _log("=" * 60 + "\n")


def _signal_handler(signum: int, frame: object) -> None:
    global _shutdown_requested
    if _shutdown_requested:
        print("\nForce quit.")
        sys.exit(1)
    _shutdown_requested = True
    print("\nShutdown requested. Saving checkpoint after current question...")


def parse_args() -> BenchmarkConfig:
    parser = argparse.ArgumentParser(
        description="LongMemEval benchmark for mem-mesh"
    )
    parser.add_argument(
        "--variant",
        choices=["s", "m"],
        default="s",
        help="Dataset variant: s (~53 sessions) or m (~500 sessions)",
    )
    parser.add_argument(
        "--topk",
        type=int,
        default=5,
        help="Number of results to retrieve (default: 5)",
    )
    parser.add_argument(
        "--search-mode",
        default="hybrid",
        choices=["hybrid", "semantic", "smart"],
        help="Search mode (default: hybrid)",
    )
    parser.add_argument(
        "--cot",
        action="store_true",
        help="Use chain-of-thought prompting",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=None,
        help="Limit number of questions (for testing)",
    )
    parser.add_argument(
        "--question-types",
        nargs="+",
        default=None,
        help="Filter by question types",
    )
    parser.add_argument(
        "--claude-model",
        default="sonnet",
        help="Claude model to use (default: sonnet)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Generate report from existing results without running",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry questions that previously had generation failures",
    )
    parser.add_argument(
        "--enable-reranking",
        action="store_true",
        help="Enable cross-encoder reranking for search results",
    )
    parser.add_argument(
        "--reranking-model",
        default=None,
        help="Cross-encoder model for reranking (default: ms-marco-multilingual-MiniLM-L6-v2)",
    )

    args = parser.parse_args()

    return BenchmarkConfig(
        variant=args.variant,
        topk=args.topk,
        search_mode=args.search_mode,
        use_cot=args.cot,
        max_questions=args.max_questions,
        question_types=args.question_types,
        claude_model=args.claude_model,
        resume=args.resume,
        report_only=args.report_only,
        retry_failed=args.retry_failed,
        enable_reranking=args.enable_reranking,
        reranking_model=args.reranking_model,
    )


async def process_question(
    question: LongMemEvalQuestion,
    embedding_service: "EmbeddingService",
    config: BenchmarkConfig,
) -> QuestionResult:
    """Process a single question through the full pipeline."""
    start = time.time()

    # Step 1: Index
    await index_question(question, embedding_service, config)

    # Step 2: Retrieve
    retrieval = await retrieve_for_question(question, embedding_service, config)

    # Step 3: Generate answer
    generated_answer, gen_time = generate_answer(question, retrieval, config)

    # Step 4: Evaluate
    is_correct, judge_response, eval_time = evaluate_answer(
        question, generated_answer, config
    )

    total_time = time.time() - start

    return QuestionResult(
        question_id=question.question_id,
        question_type=question.question_type,
        is_abstention=question.is_abstention,
        retrieved_session_ids=retrieval.retrieved_session_ids,
        recall_any=retrieval.recall_any,
        recall_all=retrieval.recall_all,
        search_time_ms=retrieval.search_time_ms,
        generated_answer=generated_answer,
        generation_time_s=gen_time,
        is_correct=is_correct,
        judge_response=judge_response,
        eval_time_s=eval_time,
        total_time_s=total_time,
    )


async def run_benchmark(config: BenchmarkConfig) -> None:
    """Main benchmark execution loop."""
    global _shutdown_requested

    # Report-only mode
    if config.report_only:
        checkpoint = load_checkpoint(config)
        if not checkpoint.results:
            _log("No results found. Run the benchmark first.")
            return
        report = generate_report(checkpoint, config)
        save_report(report, config)
        _log_report(report)
        return

    # Download dataset
    download_dataset(config)

    # Load questions
    questions = load_questions(config)
    if not questions:
        _log("No questions to process.")
        return

    # Load or create checkpoint
    checkpoint: CheckpointData
    if config.resume or config.retry_failed:
        checkpoint = load_checkpoint(config)
    else:
        checkpoint = CheckpointData()

    checkpoint.config_summary = {
        "variant": config.variant,
        "topk": config.topk,
        "search_mode": config.search_mode,
        "use_cot": config.use_cot,
        "claude_model": config.claude_model,
        "enable_reranking": config.enable_reranking,
    }

    # Determine which questions to process
    is_retry_mode = False
    if config.retry_failed:
        failed_ids = set(get_failed_question_ids(checkpoint))
        remaining = [q for q in questions if q.question_id in failed_ids]
        is_retry_mode = True
        _log(f"\nLongMemEval Benchmark (retry-failed mode)")
        _log(f"  Total: {len(questions)} | Failed to retry: {len(remaining)}")
    else:
        completed_set = set(checkpoint.completed_ids)
        remaining = [q for q in questions if q.question_id not in completed_set]
        _log(f"\nLongMemEval Benchmark")
        _log(f"  Total: {len(questions)} | Completed: {len(completed_set)} | Remaining: {len(remaining)}")

    _log(
        f"  Config: variant={config.variant} topk={config.topk} "
        f"mode={config.search_mode} cot={config.use_cot} "
        f"reranking={config.enable_reranking}"
    )
    _log("")

    if not remaining:
        if is_retry_mode:
            _log("No failed questions to retry. Generating report...")
        else:
            _log("All questions already completed. Generating report...")
        report = generate_report(checkpoint, config)
        save_report(report, config)
        _log_report(report)
        return

    # Initialize embedding service (shared across all questions)
    from app.core.embeddings.service import EmbeddingService

    _log("Loading embedding model...")
    embedding_service = EmbeddingService(preload=True)
    _log(f"  Model: {embedding_service.get_model_info()}")

    # Process questions
    correct_count = 0
    total_processed = len(checkpoint.completed_ids)

    for i, question in enumerate(remaining, 1):
        if _shutdown_requested:
            _log(f"\nSaving checkpoint ({total_processed} completed)...")
            save_checkpoint(config, checkpoint)
            report = generate_report(checkpoint, config)
            save_report(report, config)
            _log_report(report)
            return

        _log(
            f"[{total_processed + 1}/{len(questions)}] "
            f"{question.question_id} ({question.question_type})"
            f"{' [ABS]' if question.is_abstention else ''} ... ",
            end="",
        )

        try:
            result = await process_question(question, embedding_service, config)
            if is_retry_mode:
                update_result(checkpoint, result)
            else:
                add_result(checkpoint, result)
            save_checkpoint(config, checkpoint)

            total_processed += 1
            if result.is_correct:
                correct_count += 1

            status = "OK" if result.is_correct else "WRONG"
            _log(
                f"{status}  "
                f"(recall={result.recall_any:.0f} "
                f"gen={result.generation_time_s:.1f}s "
                f"eval={result.eval_time_s:.1f}s "
                f"total={result.total_time_s:.1f}s)  "
                f"[running: {correct_count}/{i}={correct_count/i:.1%}]"
            )

        except Exception as e:
            _log(f"ERROR: {e}")
            logger.exception("Error processing %s", question.question_id)
            # Save checkpoint and continue
            save_checkpoint(config, checkpoint)
            continue

    # Final report
    _log(f"\nBenchmark complete! ({total_processed} questions)")
    report = generate_report(checkpoint, config)
    save_report(report, config)
    _log_report(report)


def main() -> None:
    global _LOG_FILE

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Reduce noise from internal modules
    logging.getLogger("app.core").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    config = parse_args()

    # Open persistent log file
    config.results_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.results_dir / "benchmark.log"
    _LOG_FILE = open(log_path, "a", encoding="utf-8")
    _log(f"\n{'='*40} Run started at {time.strftime('%Y-%m-%d %H:%M:%S')} {'='*40}")

    try:
        asyncio.run(run_benchmark(config))
    finally:
        if _LOG_FILE:
            _LOG_FILE.close()
            _LOG_FILE = None


if __name__ == "__main__":
    main()
