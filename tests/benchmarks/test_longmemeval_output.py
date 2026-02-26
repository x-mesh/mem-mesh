"""Unit tests for LongMemEval benchmark output modules.

Tests generator.build_context, evaluator helpers, reporter, and translator I/O.
Does NOT call any LLM functions.
"""

import json
from pathlib import Path
from typing import List

import pytest

from app.core.schemas.responses import SearchResult
from benchmarks.longmemeval.evaluator import is_abstention_answer, is_abstention_type
from benchmarks.longmemeval.generator import build_context
from benchmarks.longmemeval.models import (
    BenchmarkReport,
    CategoryReport,
    QuestionResult,
    RetrievalMetrics,
)
from benchmarks.longmemeval.reporter import (
    generate_report,
    print_report,
    save_report_json,
    save_report_markdown,
)
from benchmarks.longmemeval.translator import _load_existing, _parse_json, _save_results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_search_result(content: str, score: float) -> SearchResult:
    return SearchResult(
        id="mem_001",
        content=content,
        similarity_score=score,
        created_at="2024-01-15T10:30:00Z",
        project_id="test",
        category="task",
        source="test",
        tags=None,
    )


def _make_question_result(
    qid: str,
    qtype: str,
    eval_label: int,
    recall_any_10: float = 1.0,
    recall_all_10: float = 1.0,
    time_ms: float = 10.0,
) -> QuestionResult:
    return QuestionResult(
        question_id=qid,
        question_type=qtype,
        question="What happened?",
        answer="Something",
        hypothesis="Something happened",
        retrieval_metrics=RetrievalMetrics(
            recall_any={1: recall_any_10, 3: recall_any_10, 5: recall_any_10, 10: recall_any_10},
            recall_all={1: recall_all_10, 3: recall_all_10, 5: recall_all_10, 10: recall_all_10},
            ndcg={1: 1.0, 3: 1.0, 5: 1.0, 10: 1.0},
            retrieval_time_ms=time_ms,
        ),
        eval_label=eval_label,
    )


@pytest.fixture
def search_results() -> List[SearchResult]:
    return [
        _make_search_result("First conversation about cats.", 0.95),
        _make_search_result("Second conversation about dogs.", 0.82),
    ]


@pytest.fixture
def question_results() -> List[QuestionResult]:
    return [
        _make_question_result("q_001", "single-session-user-centric", 1),
        _make_question_result("q_002", "single-session-user-centric", 0),
        _make_question_result("q_003", "multi-session-temporal", 1),
        _make_question_result("q_004", "multi-session-temporal", 1),
    ]


@pytest.fixture
def sample_report(question_results: List[QuestionResult]) -> BenchmarkReport:
    return generate_report(
        results=question_results,
        experiment_name="test-run",
        language="en",
        indexing_strategy="session",
    )


# ===========================================================================
# 1. generator.build_context
# ===========================================================================


class TestBuildContext:
    def test_multiple_results(self, search_results: List[SearchResult]) -> None:
        ctx = build_context(search_results)
        assert "Context 1 (score: 0.950)" in ctx
        assert "First conversation about cats." in ctx
        assert "Context 2 (score: 0.820)" in ctx
        assert "Second conversation about dogs." in ctx

    def test_empty_results(self) -> None:
        ctx = build_context([])
        assert ctx == ""


# ===========================================================================
# 2. evaluator helpers
# ===========================================================================


class TestIsAbstentionType:
    def test_abs_suffix(self) -> None:
        assert is_abstention_type("single-session-user-centric_abs") is True

    def test_no_abs_suffix(self) -> None:
        assert is_abstention_type("single-session-user-centric") is False

    def test_abs_in_middle(self) -> None:
        assert is_abstention_type("abs_something") is False


class TestIsAbstentionAnswer:
    @pytest.mark.parametrize(
        "text",
        [
            "I don't know the answer.",
            "I cannot answer based on the available information.",
            "I'm not sure about that.",
            "There is insufficient information to answer.",
            "No information available in the context.",
            "Cannot determine the answer.",
            "Unable to answer this question.",
        ],
    )
    def test_english_abstention(self, text: str) -> None:
        assert is_abstention_answer(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "모르겠습니다.",
            "답할 수 없습니다.",
            "알 수 없는 정보입니다.",
            "정보가 부족합니다.",
            "확인할 수 없습니다.",
        ],
    )
    def test_korean_abstention(self, text: str) -> None:
        assert is_abstention_answer(text) is True

    def test_non_abstention(self) -> None:
        assert is_abstention_answer("The meeting was on Tuesday.") is False

    def test_case_insensitive(self) -> None:
        assert is_abstention_answer("I DON'T KNOW") is True


# ===========================================================================
# 3. reporter
# ===========================================================================


class TestGenerateReport:
    def test_overall_accuracy(self, question_results: List[QuestionResult]) -> None:
        report = generate_report(results=question_results, experiment_name="acc-test")
        # 3 correct out of 4
        assert report.overall_accuracy == pytest.approx(0.75)
        assert report.total_questions == 4
        assert report.evaluated_questions == 4

    def test_category_breakdown(self, question_results: List[QuestionResult]) -> None:
        report = generate_report(results=question_results, experiment_name="cat-test")
        cats = {c.category: c for c in report.category_results}
        assert "single-session-user-centric" in cats
        assert "multi-session-temporal" in cats

        single = cats["single-session-user-centric"]
        assert single.total == 2
        assert single.correct == 1
        assert single.accuracy == pytest.approx(0.5)

        multi = cats["multi-session-temporal"]
        assert multi.total == 2
        assert multi.correct == 2
        assert multi.accuracy == pytest.approx(1.0)

    def test_avg_retrieval_metrics(self, question_results: List[QuestionResult]) -> None:
        report = generate_report(results=question_results, experiment_name="ret-test")
        m = report.avg_retrieval_metrics
        assert m.recall_any[10] == pytest.approx(1.0)
        assert m.recall_all[10] == pytest.approx(1.0)
        assert m.ndcg[10] == pytest.approx(1.0)
        assert m.retrieval_time_ms == pytest.approx(10.0)

    def test_empty_results(self) -> None:
        report = generate_report(results=[], experiment_name="empty")
        assert report.overall_accuracy == 0.0
        assert report.total_questions == 0
        assert report.evaluated_questions == 0
        assert report.category_results == []

    def test_results_with_none_eval_label(self) -> None:
        results = [
            _make_question_result("q_001", "type_a", 1),
            QuestionResult(
                question_id="q_002",
                question_type="type_a",
                question="What?",
                answer="Nothing",
                hypothesis="Nothing",
                eval_label=None,
            ),
        ]
        report = generate_report(results=results, experiment_name="partial")
        assert report.total_questions == 2
        assert report.evaluated_questions == 1
        assert report.overall_accuracy == pytest.approx(1.0)


class TestPrintReport:
    def test_runs_without_error(self, sample_report: BenchmarkReport, capsys: pytest.CaptureFixture[str]) -> None:
        print_report(sample_report)
        captured = capsys.readouterr()
        assert "test-run" in captured.out
        assert "Overall Accuracy" in captured.out


class TestSaveReportMarkdown:
    def test_writes_valid_markdown(self, sample_report: BenchmarkReport, tmp_path: Path) -> None:
        md_path = str(tmp_path / "report.md")
        save_report_markdown(sample_report, md_path)

        content = Path(md_path).read_text(encoding="utf-8")
        assert content.startswith("# LongMemEval Results:")
        assert "| Category |" in content
        assert "single-session-user-centric" in content

    def test_creates_parent_dirs(self, sample_report: BenchmarkReport, tmp_path: Path) -> None:
        md_path = str(tmp_path / "sub" / "dir" / "report.md")
        save_report_markdown(sample_report, md_path)
        assert Path(md_path).exists()


class TestSaveReportJson:
    def test_writes_valid_json(self, sample_report: BenchmarkReport, tmp_path: Path) -> None:
        json_path = str(tmp_path / "report.json")
        save_report_json(sample_report, json_path)

        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        assert data["experiment_name"] == "test-run"
        assert isinstance(data["category_results"], list)
        assert isinstance(data["avg_retrieval_metrics"], dict)

    def test_creates_parent_dirs(self, sample_report: BenchmarkReport, tmp_path: Path) -> None:
        json_path = str(tmp_path / "sub" / "dir" / "report.json")
        save_report_json(sample_report, json_path)
        assert Path(json_path).exists()


# ===========================================================================
# 4. translator helpers
# ===========================================================================


class TestParseJson:
    def test_raw_json_object(self) -> None:
        result = _parse_json('{"question": "무엇?", "answer": "답변"}')
        assert result == {"question": "무엇?", "answer": "답변"}

    def test_raw_json_array(self) -> None:
        result = _parse_json('["hello", "world"]')
        assert result == ["hello", "world"]

    def test_code_block_json(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        result = _parse_json(text)
        assert result == {"key": "value"}

    def test_code_block_plain(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = _parse_json(text)
        assert result == {"key": "value"}

    def test_invalid_json_returns_none(self) -> None:
        result = _parse_json("not json at all")
        assert result is None


class TestLoadExisting:
    def test_existing_file(self, tmp_path: Path) -> None:
        data = [{"question_id": "q1", "question": "hi"}]
        p = tmp_path / "existing.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = _load_existing(str(p))
        assert result == data

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        result = _load_existing(str(tmp_path / "missing.json"))
        assert result == []

    def test_corrupt_file(self, tmp_path: Path) -> None:
        p = tmp_path / "corrupt.json"
        p.write_text("not-json", encoding="utf-8")
        result = _load_existing(str(p))
        assert result == []


class TestSaveResults:
    def test_writes_json(self, tmp_path: Path) -> None:
        data = [{"question_id": "q1"}]
        out = str(tmp_path / "output.json")
        _save_results(data, out)
        loaded = json.loads(Path(out).read_text(encoding="utf-8"))
        assert loaded == data

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = str(tmp_path / "a" / "b" / "out.json")
        _save_results([{"x": 1}], out)
        assert Path(out).exists()
