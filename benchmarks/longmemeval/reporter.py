"""결과 리포트 (Markdown + JSON + console)"""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from .models import (
    BenchmarkReport,
    CategoryReport,
    QuestionResult,
    RetrievalMetrics,
)

logger = logging.getLogger(__name__)


def generate_report(
    results: List[QuestionResult],
    experiment_name: str = "",
    language: str = "en",
    indexing_strategy: str = "session",
    config_summary: Optional[Dict[str, str]] = None,
) -> BenchmarkReport:
    """결과를 집계하여 BenchmarkReport 생성

    Args:
        results: 질문 결과 리스트
        experiment_name: 실험 이름
        language: 언어
        indexing_strategy: 인덱싱 전략
        config_summary: 설정 요약

    Returns:
        BenchmarkReport
    """
    evaluated = [r for r in results if r.eval_label is not None]

    # 전체 정확도
    correct_count = sum(1 for r in evaluated if r.eval_label == 1)
    overall_accuracy = (
        correct_count / len(evaluated) if evaluated else 0.0
    )

    # 카테고리별 집계
    by_type: Dict[str, List[QuestionResult]] = defaultdict(list)
    for r in evaluated:
        by_type[r.question_type].append(r)

    category_results: List[CategoryReport] = []
    for qtype, type_results in sorted(by_type.items()):
        type_correct = sum(
            1 for r in type_results if r.eval_label == 1
        )
        type_accuracy = type_correct / len(type_results)

        # 평균 recall_any@10
        recall_any_10_values = [
            r.retrieval_metrics.recall_any.get(10, 0.0)
            for r in type_results
        ]
        avg_recall_any = (
            sum(recall_any_10_values) / len(recall_any_10_values)
            if recall_any_10_values
            else 0.0
        )

        # 평균 recall_all@10
        recall_all_10_values = [
            r.retrieval_metrics.recall_all.get(10, 0.0)
            for r in type_results
        ]
        avg_recall_all = (
            sum(recall_all_10_values) / len(recall_all_10_values)
            if recall_all_10_values
            else 0.0
        )

        # 평균 retrieval time
        time_values = [
            r.retrieval_metrics.retrieval_time_ms
            for r in type_results
        ]
        avg_time = (
            sum(time_values) / len(time_values)
            if time_values
            else 0.0
        )

        category_results.append(
            CategoryReport(
                category=qtype,
                total=len(type_results),
                correct=type_correct,
                accuracy=type_accuracy,
                avg_recall_any_at_10=avg_recall_any,
                avg_recall_all_at_10=avg_recall_all,
                avg_retrieval_time_ms=avg_time,
            )
        )

    # 평균 검색 메트릭
    avg_metrics = _average_metrics(evaluated)

    return BenchmarkReport(
        experiment_name=experiment_name,
        language=language,
        indexing_strategy=indexing_strategy,
        total_questions=len(results),
        evaluated_questions=len(evaluated),
        overall_accuracy=overall_accuracy,
        category_results=category_results,
        avg_retrieval_metrics=avg_metrics,
        config_summary=config_summary or {},
    )


def _average_metrics(
    results: List[QuestionResult],
) -> RetrievalMetrics:
    """평균 검색 메트릭 계산"""
    if not results:
        return RetrievalMetrics()

    ks = [1, 3, 5, 10]
    avg_recall_any: Dict[int, float] = {}
    avg_recall_all: Dict[int, float] = {}
    avg_ndcg: Dict[int, float] = {}

    for k in ks:
        ra_values = [
            r.retrieval_metrics.recall_any.get(k, 0.0) for r in results
        ]
        avg_recall_any[k] = sum(ra_values) / len(ra_values)

        rall_values = [
            r.retrieval_metrics.recall_all.get(k, 0.0) for r in results
        ]
        avg_recall_all[k] = sum(rall_values) / len(rall_values)

        ndcg_values = [
            r.retrieval_metrics.ndcg.get(k, 0.0) for r in results
        ]
        avg_ndcg[k] = sum(ndcg_values) / len(ndcg_values)

    avg_time = sum(
        r.retrieval_metrics.retrieval_time_ms for r in results
    ) / len(results)

    return RetrievalMetrics(
        recall_any=avg_recall_any,
        recall_all=avg_recall_all,
        ndcg=avg_ndcg,
        retrieval_time_ms=avg_time,
    )


def print_report(report: BenchmarkReport) -> None:
    """콘솔에 리포트 출력"""
    print("\n" + "=" * 70)
    print(f"  LongMemEval Results: {report.experiment_name}")
    print("=" * 70)
    print(f"  Language: {report.language}")
    print(f"  Indexing: {report.indexing_strategy}")
    print(
        f"  Questions: {report.evaluated_questions}/{report.total_questions}"
    )
    print(f"  Overall Accuracy: {report.overall_accuracy:.1%}")
    print("-" * 70)

    # 카테고리별 결과
    print(
        f"  {'Category':<35} {'Acc':>7} {'N':>5} "
        f"{'R_any@10':>9} {'R_all@10':>9} {'Time(ms)':>9}"
    )
    print("-" * 70)
    for cat in report.category_results:
        print(
            f"  {cat.category:<35} {cat.accuracy:>6.1%} {cat.total:>5} "
            f"{cat.avg_recall_any_at_10:>8.1%} {cat.avg_recall_all_at_10:>8.1%} "
            f"{cat.avg_retrieval_time_ms:>8.1f}"
        )

    # 평균 검색 메트릭
    print("-" * 70)
    m = report.avg_retrieval_metrics
    for k in [1, 3, 5, 10]:
        ra = m.recall_any.get(k, 0)
        rall = m.recall_all.get(k, 0)
        ndcg = m.ndcg.get(k, 0)
        print(
            f"  @{k:<3}  recall_any: {ra:.3f}  "
            f"recall_all: {rall:.3f}  ndcg: {ndcg:.3f}"
        )
    print(f"  Avg retrieval time: {m.retrieval_time_ms:.1f}ms")
    print("=" * 70 + "\n")


def save_report_markdown(
    report: BenchmarkReport, output_path: str
) -> None:
    """Markdown 리포트 저장"""
    lines: List[str] = [
        f"# LongMemEval Results: {report.experiment_name}",
        "",
        f"- **Language**: {report.language}",
        f"- **Indexing Strategy**: {report.indexing_strategy}",
        f"- **Questions**: {report.evaluated_questions}/{report.total_questions}",
        f"- **Overall Accuracy**: {report.overall_accuracy:.1%}",
        "",
        "## Results by Category",
        "",
        "| Category | Accuracy | N | R_any@10 | R_all@10 |",
        "|----------|----------|---|----------|----------|",
    ]

    for cat in report.category_results:
        lines.append(
            f"| {cat.category} | {cat.accuracy:.1%} | {cat.total} | "
            f"{cat.avg_recall_any_at_10:.1%} | {cat.avg_recall_all_at_10:.1%} |"
        )

    lines.extend(
        [
            "",
            "## Comparison",
            "",
            "| System | Overall |",
            "|--------|---------|",
            f"| **mem-mesh** | **{report.overall_accuracy:.1%}** |",
            "| OMEGA Memory | 95.4% |",
            "| GPT-4o (RAG) | 72% |",
            "",
            "## Retrieval Metrics",
            "",
            "| k | recall_any | recall_all | NDCG |",
            "|---|------------|------------|------|",
        ]
    )

    m = report.avg_retrieval_metrics
    for k in [1, 3, 5, 10]:
        ra = m.recall_any.get(k, 0)
        rall = m.recall_all.get(k, 0)
        ndcg = m.ndcg.get(k, 0)
        lines.append(f"| {k} | {ra:.3f} | {rall:.3f} | {ndcg:.3f} |")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info(f"Markdown report saved to {output_path}")


def save_report_json(
    report: BenchmarkReport, output_path: str
) -> None:
    """JSON 리포트 저장"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            report.model_dump(), f, ensure_ascii=False, indent=2
        )
    logger.info(f"JSON report saved to {output_path}")
