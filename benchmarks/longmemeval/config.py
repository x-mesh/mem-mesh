"""Benchmark configuration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


BENCH_DIR = Path(__file__).parent
DEFAULT_DATA_DIR = BENCH_DIR / "data"
DEFAULT_RESULTS_DIR = BENCH_DIR / "results"
DEFAULT_DBS_DIR = BENCH_DIR / "dbs"


@dataclass
class BenchmarkConfig:
    """Configuration for LongMemEval benchmark run."""

    # Dataset
    variant: str = "s"  # "s" (small ~53 sessions) or "m" (medium ~500)
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)

    # Filtering
    max_questions: Optional[int] = None
    question_types: Optional[list[str]] = None
    question_ids: Optional[list[str]] = None

    # Retrieval
    search_mode: str = "hybrid"
    topk: int = 5
    enable_korean_optimization: bool = False

    # Generation
    claude_model: str = "sonnet"
    use_cot: bool = False
    generation_timeout: int = 120
    generation_retries: int = 3

    # Paths
    dbs_dir: Path = field(default_factory=lambda: DEFAULT_DBS_DIR)
    results_dir: Path = field(default_factory=lambda: DEFAULT_RESULTS_DIR)

    # Checkpoint
    resume: bool = False
    retry_failed: bool = False

    # Report
    report_only: bool = False

    @property
    def dataset_filename(self) -> str:
        return f"longmemeval_{self.variant}_cleaned.json"

    @property
    def dataset_path(self) -> Path:
        return self.data_dir / self.dataset_filename

    @property
    def checkpoint_path(self) -> Path:
        return self.results_dir / "progress.json"

    @property
    def report_path(self) -> Path:
        return self.results_dir / "report.json"

    def db_path_for(self, question_id: str) -> Path:
        return self.dbs_dir / f"{question_id}.db"
