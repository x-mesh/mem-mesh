"""LongMemEval 벤치마크 설정"""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class DatasetConfig(BaseModel):
    """데이터셋 설정"""

    name: str = "xiaowu0162/longmemeval-cleaned"
    split: str = "test"
    language: str = "en"


class IndexingConfig(BaseModel):
    """인덱싱 설정"""

    strategy: str = "session"
    window_size: int = 5
    window_overlap: int = 1
    include_date_in_content: bool = True
    max_content_length: int = 9500


class RetrievalConfig(BaseModel):
    """검색 설정"""

    top_k: int = Field(default=10, ge=1, le=20)
    search_mode: str = "hybrid"
    recency_weight: float = 0.0


class GenerationConfig(BaseModel):
    """LLM 생성 설정"""

    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.0
    max_tokens: int = 256


class EvaluationConfig(BaseModel):
    """평가 설정"""

    judge_model: str = "gpt-4o"
    temperature: float = 0.0


class ExecutionConfig(BaseModel):
    """실행 설정"""

    db_path: str = "benchmarks/longmemeval/data/benchmark_lme.db"
    checkpoint_interval: int = 50
    max_questions: Optional[int] = None
    resume_from_checkpoint: bool = True
    results_dir: str = "benchmarks/longmemeval/results"


class BenchmarkConfig(BaseModel):
    """전체 벤치마크 설정"""

    experiment_name: str = "mem-mesh-longmemeval"
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)


def load_config(config_path: Optional[str] = None) -> BenchmarkConfig:
    """YAML 설정 파일 로드

    Args:
        config_path: 설정 파일 경로. None이면 기본 config.yaml 사용.

    Returns:
        BenchmarkConfig 인스턴스
    """
    if config_path is None:
        config_path = str(
            Path(__file__).parent / "config.yaml"
        )

    path = Path(config_path)
    if not path.exists():
        return BenchmarkConfig()

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return BenchmarkConfig(**raw)
