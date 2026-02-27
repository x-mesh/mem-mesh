"""Generate benchmark reports from checkpoint results."""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .checkpoint import CheckpointData
from .config import BenchmarkConfig

logger = logging.getLogger(__name__)

QUESTION_TYPES = [
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
]


@dataclass
class CategoryMetrics:
    """Metrics for a single question category."""

    count: int = 0
    correct: int = 0
    recall_any_sum: float = 0.0
    recall_all_sum: float = 0.0
    search_time_ms_sum: float = 0.0
    gen_time_s_sum: float = 0.0
    eval_time_s_sum: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.count if self.count > 0 else 0.0

    @property
    def recall_any_avg(self) -> float:
        return self.recall_any_sum / self.count if self.count > 0 else 0.0

    @property
    def recall_all_avg(self) -> float:
        return self.recall_all_sum / self.count if self.count > 0 else 0.0

    @property
    def avg_search_ms(self) -> float:
        return self.search_time_ms_sum / self.count if self.count > 0 else 0.0

    @property
    def avg_gen_s(self) -> float:
        return self.gen_time_s_sum / self.count if self.count > 0 else 0.0


def generate_report(
    checkpoint: CheckpointData,
    config: BenchmarkConfig,
) -> dict:
    """Generate a comprehensive benchmark report."""
    results = checkpoint.results
    if not results:
        logger.warning("No results to report")
        return {}

    # Aggregate by category
    by_type: dict[str, CategoryMetrics] = defaultdict(CategoryMetrics)
    overall = CategoryMetrics()
    abstention = CategoryMetrics()

    for r in results:
        qtype = r["question_type"]
        is_abs = r.get("is_abstention", False)
        is_correct = r["is_correct"]

        # Overall
        overall.count += 1
        overall.correct += int(is_correct)
        overall.recall_any_sum += r["recall_any"]
        overall.recall_all_sum += r["recall_all"]
        overall.search_time_ms_sum += r["search_time_ms"]
        overall.gen_time_s_sum += r["generation_time_s"]
        overall.eval_time_s_sum += r["eval_time_s"]

        # By type
        m = by_type[qtype]
        m.count += 1
        m.correct += int(is_correct)
        m.recall_any_sum += r["recall_any"]
        m.recall_all_sum += r["recall_all"]
        m.search_time_ms_sum += r["search_time_ms"]
        m.gen_time_s_sum += r["generation_time_s"]
        m.eval_time_s_sum += r["eval_time_s"]

        # Abstention
        if is_abs:
            abstention.count += 1
            abstention.correct += int(is_correct)

    # Task-averaged accuracy (average of per-category accuracies)
    category_accuracies = [
        by_type[t].accuracy for t in QUESTION_TYPES if by_type[t].count > 0
    ]
    task_avg = (
        sum(category_accuracies) / len(category_accuracies)
        if category_accuracies
        else 0.0
    )

    report = {
        "summary": {
            "total_questions": overall.count,
            "overall_accuracy": round(overall.accuracy, 4),
            "task_averaged_accuracy": round(task_avg, 4),
            "abstention_accuracy": round(abstention.accuracy, 4) if abstention.count > 0 else None,
            "abstention_count": abstention.count,
        },
        "by_category": {},
        "retrieval_metrics": {
            "recall_any_avg": round(overall.recall_any_avg, 4),
            "recall_all_avg": round(overall.recall_all_avg, 4),
        },
        "timing": {
            "avg_search_ms": round(overall.avg_search_ms, 1),
            "avg_generation_s": round(overall.avg_gen_s, 1),
            "total_questions": overall.count,
        },
        "config": {
            "variant": config.variant,
            "topk": config.topk,
            "search_mode": config.search_mode,
            "use_cot": config.use_cot,
            "claude_model": config.claude_model,
        },
    }

    # Per-category breakdown
    for qtype in QUESTION_TYPES:
        m = by_type[qtype]
        if m.count > 0:
            report["by_category"][qtype] = {
                "count": m.count,
                "correct": m.correct,
                "accuracy": round(m.accuracy, 4),
                "recall_any": round(m.recall_any_avg, 4),
                "recall_all": round(m.recall_all_avg, 4),
            }

    return report


def print_report(report: dict) -> None:
    """Print a human-readable report to stdout."""
    if not report:
        print("No results available.")
        return

    s = report["summary"]
    print("\n" + "=" * 60)
    print("  LongMemEval Benchmark Report")
    print("=" * 60)

    print(f"\n  Total Questions:         {s['total_questions']}")
    print(f"  Overall Accuracy:        {s['overall_accuracy']:.1%}")
    print(f"  Task-Averaged Accuracy:  {s['task_averaged_accuracy']:.1%}")
    if s.get("abstention_count"):
        print(f"  Abstention Accuracy:     {s['abstention_accuracy']:.1%} ({s['abstention_count']} questions)")

    print("\n  --- Per-Category Accuracy ---")
    for qtype, data in report.get("by_category", {}).items():
        print(
            f"  {qtype:30s}  {data['accuracy']:6.1%}  "
            f"({data['correct']}/{data['count']})  "
            f"recall_any={data['recall_any']:.2f}  recall_all={data['recall_all']:.2f}"
        )

    rm = report.get("retrieval_metrics", {})
    print(f"\n  --- Retrieval Metrics ---")
    print(f"  Recall@K (any):  {rm.get('recall_any_avg', 0):.4f}")
    print(f"  Recall@K (all):  {rm.get('recall_all_avg', 0):.4f}")

    t = report.get("timing", {})
    print(f"\n  --- Timing ---")
    print(f"  Avg search:      {t.get('avg_search_ms', 0):.0f} ms")
    print(f"  Avg generation:  {t.get('avg_generation_s', 0):.1f} s")

    c = report.get("config", {})
    print(f"\n  --- Config ---")
    print(f"  variant={c.get('variant')}  topk={c.get('topk')}  "
          f"mode={c.get('search_mode')}  cot={c.get('use_cot')}  "
          f"model={c.get('claude_model')}")
    print("=" * 60 + "\n")


def save_report(report: dict, config: BenchmarkConfig) -> Path:
    """Save report as JSON file."""
    config.results_dir.mkdir(parents=True, exist_ok=True)
    path = config.report_path
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("Report saved to %s", path)
    return path
