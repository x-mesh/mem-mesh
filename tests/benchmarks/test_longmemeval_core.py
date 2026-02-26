"""LongMemEval 벤치마크 코어 모듈 단위 테스트

models.py, config.py, indexer.py, retriever.py의 순수 로직을 검증한다.
DirectStorageBackend나 LLM 호출이 필요한 부분은 테스트하지 않는다.
"""

import math
from unittest.mock import MagicMock

import pytest

from benchmarks.longmemeval.models import (
    BenchmarkItem,
    BenchmarkReport,
    CategoryReport,
    QuestionResult,
    RetrievalMetrics,
)
from benchmarks.longmemeval.config import (
    BenchmarkConfig,
    DatasetConfig,
    ExecutionConfig,
    GenerationConfig,
    IndexingConfig,
    RetrievalConfig,
    load_config,
)
from benchmarks.longmemeval.indexer import (
    SessionIndexer,
    TurnIndexer,
    WindowIndexer,
    create_indexer,
)
from benchmarks.longmemeval.retriever import (
    _compute_metrics,
    _extract_session_ids,
    _ndcg_at_k,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_item() -> BenchmarkItem:
    """2개 세션, 각 4개 발화를 가진 테스트 BenchmarkItem"""
    return BenchmarkItem(
        question_id="q-001",
        question_type="single-session-user-centric",
        question="What is the user's favorite color?",
        answer="Blue",
        question_date="2024-06-15",
        haystack_sessions=[
            [
                "User: Hi, I like the color blue.",
                "Assistant: That's a nice color!",
                "User: Thanks. I also enjoy painting.",
                "Assistant: Painting is a great hobby.",
            ],
            [
                "User: I went hiking yesterday.",
                "Assistant: How was the trail?",
                "User: It was beautiful, lots of green.",
                "Assistant: Sounds wonderful!",
            ],
        ],
        haystack_dates=["2024-06-01 10:00", "2024-06-10 14:30"],
        answer_session_ids=[0],
    )


@pytest.fixture
def long_session_item() -> BenchmarkItem:
    """max_content_length를 초과하는 세션을 가진 BenchmarkItem"""
    # 100자짜리 발화 100개 = ~10000자 → 9500 초과
    long_session = [f"User: {'x' * 95}" for _ in range(100)]
    return BenchmarkItem(
        question_id="q-long",
        question_type="multi-session",
        question="Long question",
        answer="Long answer",
        haystack_sessions=[long_session],
        haystack_dates=["2024-01-01"],
        answer_session_ids=[0],
    )


# ===========================================================================
# 1. models.py
# ===========================================================================


class TestBenchmarkItem:
    def test_creation(self, sample_item: BenchmarkItem) -> None:
        assert sample_item.question_id == "q-001"
        assert sample_item.question_type == "single-session-user-centric"
        assert len(sample_item.haystack_sessions) == 2
        assert len(sample_item.haystack_dates) == 2
        assert sample_item.answer_session_ids == [0]

    def test_serialization_roundtrip(self, sample_item: BenchmarkItem) -> None:
        data = sample_item.model_dump()
        restored = BenchmarkItem(**data)
        assert restored == sample_item

    def test_optional_question_date(self) -> None:
        item = BenchmarkItem(
            question_id="q-no-date",
            question_type="test",
            question="q",
            answer="a",
            haystack_sessions=[["hi"]],
            haystack_dates=["2024-01-01"],
            answer_session_ids=[0],
        )
        assert item.question_date is None


class TestQuestionResult:
    def test_default_values(self) -> None:
        qr = QuestionResult(
            question_id="q1",
            question_type="test",
            question="What?",
            answer="Something",
        )
        assert qr.hypothesis == ""
        assert qr.retrieved_session_ids == []
        assert isinstance(qr.retrieval_metrics, RetrievalMetrics)
        assert qr.eval_label is None
        assert qr.error is None


class TestRetrievalMetrics:
    def test_default_empty_dicts(self) -> None:
        m = RetrievalMetrics()
        assert m.recall_any == {}
        assert m.recall_all == {}
        assert m.ndcg == {}
        assert m.retrieval_time_ms == 0.0

    def test_with_values(self) -> None:
        m = RetrievalMetrics(
            recall_any={1: 1.0, 3: 1.0},
            recall_all={1: 0.0, 3: 1.0},
            ndcg={1: 0.5, 3: 0.8},
            retrieval_time_ms=42.5,
        )
        assert m.recall_any[1] == 1.0
        assert m.recall_all[3] == 1.0
        assert m.retrieval_time_ms == 42.5


class TestBenchmarkReport:
    def test_creation_with_category_results(self) -> None:
        cat = CategoryReport(
            category="single-session",
            total=10,
            correct=8,
            accuracy=0.8,
        )
        report = BenchmarkReport(
            experiment_name="test-exp",
            language="en",
            indexing_strategy="session",
            total_questions=10,
            evaluated_questions=10,
            overall_accuracy=0.8,
            category_results=[cat],
        )
        assert report.overall_accuracy == 0.8
        assert len(report.category_results) == 1
        assert report.category_results[0].category == "single-session"
        assert report.config_summary == {}

    def test_default_empty_lists(self) -> None:
        report = BenchmarkReport(
            experiment_name="e",
            language="en",
            indexing_strategy="session",
            total_questions=0,
            evaluated_questions=0,
            overall_accuracy=0.0,
        )
        assert report.category_results == []
        assert isinstance(report.avg_retrieval_metrics, RetrievalMetrics)


# ===========================================================================
# 2. config.py
# ===========================================================================


class TestLoadConfig:
    def test_load_default_config(self) -> None:
        """config.yaml이 존재하면 해당 값으로 로드"""
        cfg = load_config()
        assert isinstance(cfg, BenchmarkConfig)
        assert cfg.experiment_name == "mem-mesh-longmemeval"

    def test_load_nonexistent_returns_defaults(self, tmp_path) -> None:
        """존재하지 않는 경로이면 기본값 사용"""
        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        assert cfg.experiment_name == "mem-mesh-longmemeval"

    def test_load_empty_yaml(self, tmp_path) -> None:
        """빈 YAML 파일이면 기본값 사용"""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")
        cfg = load_config(str(empty_file))
        assert cfg.experiment_name == "mem-mesh-longmemeval"

    def test_load_partial_yaml(self, tmp_path) -> None:
        """일부 값만 있는 YAML은 나머지 기본값 적용"""
        partial = tmp_path / "partial.yaml"
        partial.write_text('experiment_name: "custom-exp"\n')
        cfg = load_config(str(partial))
        assert cfg.experiment_name == "custom-exp"
        assert cfg.dataset.language == "en"  # default


class TestBenchmarkConfigDefaults:
    def test_dataset_defaults(self) -> None:
        ds = DatasetConfig()
        assert ds.name == "xiaowu0162/longmemeval-cleaned"
        assert ds.split == "test"
        assert ds.language == "en"

    def test_indexing_defaults(self) -> None:
        ix = IndexingConfig()
        assert ix.strategy == "session"
        assert ix.window_size == 5
        assert ix.window_overlap == 1
        assert ix.include_date_in_content is True
        assert ix.max_content_length == 9500

    def test_retrieval_defaults(self) -> None:
        rt = RetrievalConfig()
        assert rt.top_k == 10
        assert rt.search_mode == "hybrid"
        assert rt.recency_weight == 0.0

    def test_generation_defaults(self) -> None:
        gn = GenerationConfig()
        assert gn.model == "claude-sonnet-4-20250514"
        assert gn.temperature == 0.0
        assert gn.max_tokens == 256

    def test_execution_defaults(self) -> None:
        ex = ExecutionConfig()
        assert ex.db_path == "benchmarks/longmemeval/data/benchmark_lme.db"
        assert ex.checkpoint_interval == 50
        assert ex.max_questions is None
        assert ex.resume_from_checkpoint is True

    def test_full_config_field_access(self) -> None:
        cfg = BenchmarkConfig()
        assert cfg.dataset.language == "en"
        assert cfg.indexing.strategy == "session"
        assert cfg.retrieval.top_k == 10
        assert cfg.generation.temperature == 0.0
        assert cfg.evaluation.judge_model == "gpt-4o"
        assert cfg.execution.results_dir == "benchmarks/longmemeval/results"


# ===========================================================================
# 3. indexer.py
# ===========================================================================


class TestSessionIndexer:
    def test_build_chunks_count(self, sample_item: BenchmarkItem) -> None:
        indexer = SessionIndexer()
        chunks = indexer.build_chunks(sample_item)
        # 2 sessions → 2 chunks (neither exceeds max_content_length)
        assert len(chunks) == 2

    def test_tags_contain_session_id(self, sample_item: BenchmarkItem) -> None:
        indexer = SessionIndexer()
        chunks = indexer.build_chunks(sample_item)
        assert "session_0" in chunks[0]["tags"]
        assert "session_1" in chunks[1]["tags"]

    def test_content_includes_date(self, sample_item: BenchmarkItem) -> None:
        indexer = SessionIndexer(include_date=True)
        chunks = indexer.build_chunks(sample_item)
        assert "[2024-06-01 10:00]" in chunks[0]["content"]
        assert "[2024-06-10 14:30]" in chunks[1]["content"]

    def test_content_excludes_date_when_disabled(
        self, sample_item: BenchmarkItem
    ) -> None:
        indexer = SessionIndexer(include_date=False)
        chunks = indexer.build_chunks(sample_item)
        assert "[2024-06-01" not in chunks[0]["content"]

    def test_session_ids_field(self, sample_item: BenchmarkItem) -> None:
        indexer = SessionIndexer()
        chunks = indexer.build_chunks(sample_item)
        assert chunks[0]["session_ids"] == [0]
        assert chunks[1]["session_ids"] == [1]

    def test_long_content_triggers_split(
        self, long_session_item: BenchmarkItem
    ) -> None:
        indexer = SessionIndexer(max_content_length=9500)
        chunks = indexer.build_chunks(long_session_item)
        # Long session should be split into multiple chunks
        assert len(chunks) > 1
        # All chunks should reference session 0
        for chunk in chunks:
            assert chunk["session_ids"] == [0]
            assert "session_0" in chunk["tags"]

    def test_date_tag_extraction(self, sample_item: BenchmarkItem) -> None:
        indexer = SessionIndexer()
        chunks = indexer.build_chunks(sample_item)
        # "2024-06-01 10:00" → date tag should be "date_2024-06-01"
        assert "date_2024-06-01" in chunks[0]["tags"]
        assert "date_2024-06-10" in chunks[1]["tags"]


class TestWindowIndexer:
    def test_sliding_window_behavior(self, sample_item: BenchmarkItem) -> None:
        # window_size=3, overlap=1 → step=2
        # session 0 has 4 utterances: windows [0:3], [2:4]
        # session 1 has 4 utterances: windows [0:3], [2:4]
        indexer = WindowIndexer(window_size=3, overlap=1)
        chunks = indexer.build_chunks(sample_item)
        assert len(chunks) == 4  # 2 windows per session * 2 sessions

    def test_window_tags(self, sample_item: BenchmarkItem) -> None:
        indexer = WindowIndexer(window_size=3, overlap=1)
        chunks = indexer.build_chunks(sample_item)
        # First chunk of session 0: window_0_3
        assert "session_0" in chunks[0]["tags"]
        assert "window_0_3" in chunks[0]["tags"]

    def test_overlap_creates_more_chunks(
        self, sample_item: BenchmarkItem
    ) -> None:
        no_overlap = WindowIndexer(window_size=2, overlap=0)
        with_overlap = WindowIndexer(window_size=2, overlap=1)
        chunks_no = no_overlap.build_chunks(sample_item)
        chunks_yes = with_overlap.build_chunks(sample_item)
        assert len(chunks_yes) >= len(chunks_no)

    def test_window_content_includes_date(
        self, sample_item: BenchmarkItem
    ) -> None:
        indexer = WindowIndexer(window_size=2, overlap=0, include_date=True)
        chunks = indexer.build_chunks(sample_item)
        for chunk in chunks:
            assert chunk["content"].startswith("[")


class TestTurnIndexer:
    def test_pairs_utterances(self, sample_item: BenchmarkItem) -> None:
        indexer = TurnIndexer()
        chunks = indexer.build_chunks(sample_item)
        # Each session has 4 utterances → 2 turns per session → 4 turns total
        assert len(chunks) == 4

    def test_turn_tags(self, sample_item: BenchmarkItem) -> None:
        indexer = TurnIndexer()
        chunks = indexer.build_chunks(sample_item)
        # First turn of session 0
        assert "session_0" in chunks[0]["tags"]
        assert "turn_0" in chunks[0]["tags"]
        # Second turn of session 0
        assert "session_0" in chunks[1]["tags"]
        assert "turn_1" in chunks[1]["tags"]

    def test_turn_content_has_two_utterances(
        self, sample_item: BenchmarkItem
    ) -> None:
        indexer = TurnIndexer(include_date=False)
        chunks = indexer.build_chunks(sample_item)
        # Each turn chunk should have exactly 2 utterances (lines)
        lines = chunks[0]["content"].split("\n")
        assert len(lines) == 2

    def test_odd_utterance_count(self) -> None:
        """홀수 발화 세션: 마지막 턴은 1개 발화만 포함"""
        item = BenchmarkItem(
            question_id="q-odd",
            question_type="test",
            question="q",
            answer="a",
            haystack_sessions=[["u1", "a1", "u2"]],
            haystack_dates=["2024-01-01"],
            answer_session_ids=[0],
        )
        indexer = TurnIndexer(include_date=False)
        chunks = indexer.build_chunks(item)
        assert len(chunks) == 2  # turn_0: [u1,a1], turn_1: [u2]
        assert chunks[1]["content"] == "u2"


class TestCreateIndexer:
    def test_session_strategy(self) -> None:
        indexer = create_indexer("session")
        assert isinstance(indexer, SessionIndexer)

    def test_window_strategy(self) -> None:
        indexer = create_indexer("window", window_size=3, window_overlap=1)
        assert isinstance(indexer, WindowIndexer)
        assert indexer.window_size == 3
        assert indexer.overlap == 1

    def test_turn_strategy(self) -> None:
        indexer = create_indexer("turn")
        assert isinstance(indexer, TurnIndexer)

    def test_unknown_strategy_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown indexing strategy"):
            create_indexer("unknown")

    def test_include_date_param(self) -> None:
        indexer = create_indexer("session", include_date=False)
        assert indexer.include_date is False

    def test_max_content_length_param(self) -> None:
        indexer = create_indexer("session", max_content_length=5000)
        assert indexer.max_content_length == 5000


# ===========================================================================
# 4. retriever.py (pure functions only)
# ===========================================================================


def _make_search_result(tags: list[str] | None = None) -> MagicMock:
    """SearchResult 목 객체 생성"""
    result = MagicMock()
    result.tags = tags
    return result


class TestExtractSessionIds:
    def test_extracts_from_tags(self) -> None:
        results = [
            _make_search_result(["session_0", "window_0_3"]),
            _make_search_result(["session_2", "date_2024-01-01"]),
        ]
        ids = _extract_session_ids(results)
        assert ids == [0, 2]

    def test_deduplicates(self) -> None:
        results = [
            _make_search_result(["session_1", "part_0"]),
            _make_search_result(["session_1", "part_1"]),
        ]
        ids = _extract_session_ids(results)
        assert ids == [1]

    def test_handles_missing_tags(self) -> None:
        results = [
            _make_search_result(None),
            _make_search_result(["session_3"]),
        ]
        ids = _extract_session_ids(results)
        assert ids == [3]

    def test_empty_results(self) -> None:
        ids = _extract_session_ids([])
        assert ids == []

    def test_preserves_order(self) -> None:
        results = [
            _make_search_result(["session_5"]),
            _make_search_result(["session_2"]),
            _make_search_result(["session_8"]),
        ]
        ids = _extract_session_ids(results)
        assert ids == [5, 2, 8]

    def test_ignores_non_session_tags(self) -> None:
        results = [
            _make_search_result(["date_2024-01-01", "window_0_3"]),
        ]
        ids = _extract_session_ids(results)
        assert ids == []


class TestComputeMetrics:
    def test_perfect_match(self) -> None:
        """모든 정답 세션이 top-1에 포함"""
        retrieved = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        answer_set = {0}
        m = _compute_metrics(retrieved, answer_set, 10.0)

        assert m.recall_any[1] == 1.0
        assert m.recall_any[10] == 1.0
        assert m.recall_all[1] == 1.0
        assert m.recall_all[10] == 1.0
        assert m.ndcg[1] == pytest.approx(1.0)
        assert m.retrieval_time_ms == 10.0

    def test_partial_match(self) -> None:
        """정답 세션이 2개이고 하나만 top-1에 포함"""
        retrieved = [0, 5, 2, 3, 4, 1, 6, 7, 8, 9]
        answer_set = {0, 1}
        m = _compute_metrics(retrieved, answer_set, 5.0)

        # recall_any@1: session 0 is at position 0 → hit
        assert m.recall_any[1] == 1.0
        # recall_all@1: only session 0 in top-1, session 1 missing
        assert m.recall_all[1] == 0.0
        # recall_all@10: both sessions in top-10
        assert m.recall_all[10] == 1.0

    def test_no_match(self) -> None:
        """정답 세션이 검색 결과에 없음"""
        retrieved = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        answer_set = {0, 1}
        m = _compute_metrics(retrieved, answer_set, 1.0)

        for k in [1, 3, 5, 10]:
            assert m.recall_any[k] == 0.0
            assert m.recall_all[k] == 0.0
            assert m.ndcg[k] == 0.0

    def test_empty_answer_set(self) -> None:
        """정답 세션이 없으면 모든 메트릭 0"""
        retrieved = [0, 1, 2]
        m = _compute_metrics(retrieved, set(), 2.0)

        for k in [1, 3, 5, 10]:
            assert m.recall_any[k] == 0.0
            assert m.recall_all[k] == 0.0
            assert m.ndcg[k] == 0.0

    def test_empty_retrieved(self) -> None:
        """검색 결과가 비어있으면 모든 메트릭 0"""
        m = _compute_metrics([], {0, 1}, 3.0)

        for k in [1, 3, 5, 10]:
            assert m.recall_any[k] == 0.0
            assert m.recall_all[k] == 0.0
            assert m.ndcg[k] == 0.0

    def test_metric_keys(self) -> None:
        """k = [1, 3, 5, 10] 키가 모두 존재"""
        m = _compute_metrics([0], {0}, 1.0)
        for k in [1, 3, 5, 10]:
            assert k in m.recall_any
            assert k in m.recall_all
            assert k in m.ndcg


class TestNdcgAtK:
    def test_perfect_single(self) -> None:
        """정답 1개가 1위에 있으면 NDCG=1.0"""
        score = _ndcg_at_k([0], {0}, 1)
        assert score == pytest.approx(1.0)

    def test_perfect_multiple(self) -> None:
        """정답 2개가 1, 2위에 있으면 NDCG=1.0"""
        score = _ndcg_at_k([0, 1, 2, 3], {0, 1}, 4)
        assert score == pytest.approx(1.0)

    def test_dcg_calculation(self) -> None:
        """수동 DCG/IDCG 계산과 일치하는지 확인"""
        # retrieved: [5, 0, 1], answer_set: {0, 1}, k=3
        # Relevance: [0, 1, 1]
        # DCG = 0/log2(2) + 1/log2(3) + 1/log2(4) = 0 + 0.6309 + 0.5 = 1.1309
        # IDCG (ideal: [1, 1, 0]) = 1/log2(2) + 1/log2(3) + 0/log2(4) = 1.0 + 0.6309 = 1.6309
        # NDCG = 1.1309 / 1.6309 ≈ 0.6934
        score = _ndcg_at_k([5, 0, 1], {0, 1}, 3)
        expected_dcg = 0 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
        expected_idcg = 1 / math.log2(2) + 1 / math.log2(3) + 0 / math.log2(4)
        expected_ndcg = expected_dcg / expected_idcg
        assert score == pytest.approx(expected_ndcg, abs=1e-4)

    def test_no_relevant_docs(self) -> None:
        """정답이 없으면 NDCG=0"""
        score = _ndcg_at_k([5, 6, 7], {0, 1}, 3)
        assert score == pytest.approx(0.0)

    def test_empty_retrieved(self) -> None:
        """검색 결과 없으면 NDCG=0"""
        score = _ndcg_at_k([], {0}, 3)
        assert score == pytest.approx(0.0)
