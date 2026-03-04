"""LongMemEval 벤치마크 오케스트레이터

전체 파이프라인: 데이터 로드 → 인덱싱 → 검색 → 생성 → 평가 → 리포트
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from app.core.storage.direct import DirectStorageBackend

from .config import BenchmarkConfig
from .dataset import load_dataset
from .evaluator import evaluate_answer
from .generator import generate_answer
from .indexer import create_indexer
from .models import BenchmarkItem, QuestionResult
from .reporter import (
    generate_report,
    print_report,
    save_report_json,
    save_report_markdown,
)
from .retriever import Retriever

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """벤치마크 파이프라인 실행기"""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.storage: Optional[DirectStorageBackend] = None
        self.results: List[QuestionResult] = []
        self._results_path = self._get_results_path()

    def _get_results_path(self) -> str:
        """결과 JSONL 파일 경로"""
        lang = self.config.dataset.language
        strategy = self.config.indexing.strategy
        return os.path.join(
            self.config.execution.results_dir,
            f"{lang}_{strategy}.jsonl",
        )

    async def initialize(self) -> None:
        """스토리지 백엔드 초기화"""
        db_path = self.config.execution.db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.storage = DirectStorageBackend(db_path)
        await self.storage.initialize()
        logger.info(f"Storage initialized: {db_path}")

    async def shutdown(self) -> None:
        """스토리지 백엔드 종료"""
        if self.storage:
            await self.storage.shutdown()
            self.storage = None

    async def run(self) -> None:
        """전체 파이프라인 실행"""
        try:
            from tqdm.asyncio import tqdm as atqdm
        except ImportError:
            atqdm = None

        await self.initialize()

        try:
            # 데이터셋 로드
            items = load_dataset(self.config)
            logger.info(f"Loaded {len(items)} items")

            # 체크포인트에서 복원
            completed_ids = self._load_checkpoint()
            logger.info(f"Checkpoint: {len(completed_ids)} items already completed")

            # 인덱서 / 리트리버 생성
            indexer = create_indexer(
                strategy=self.config.indexing.strategy,
                window_size=self.config.indexing.window_size,
                window_overlap=self.config.indexing.window_overlap,
                include_date=self.config.indexing.include_date_in_content,
                max_content_length=self.config.indexing.max_content_length,
            )
            retriever = Retriever(
                storage=self.storage,
                top_k=self.config.retrieval.top_k,
                search_mode=self.config.retrieval.search_mode,
                recency_weight=self.config.retrieval.recency_weight,
            )

            # 진행률 표시
            pending = [
                item for item in items if item.question_id not in completed_ids
            ]
            iterator = enumerate(pending)
            if atqdm is not None:
                # tqdm 래핑은 별도로
                pass

            for idx, item in iterator:
                try:
                    result = await self._process_item(
                        item, indexer, retriever
                    )
                    self.results.append(result)
                    self._append_result(result)

                    # 진행 상황
                    total_done = len(completed_ids) + idx + 1
                    if total_done % 10 == 0:
                        logger.info(
                            f"Progress: {total_done}/{len(items)}"
                        )

                    # 체크포인트
                    if (
                        total_done % self.config.execution.checkpoint_interval == 0
                    ):
                        logger.info(
                            f"Checkpoint at {total_done}/{len(items)}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error processing {item.question_id}: {e}"
                    )
                    error_result = QuestionResult(
                        question_id=item.question_id,
                        question_type=item.question_type,
                        question=item.question,
                        answer=item.answer,
                        error=str(e),
                    )
                    self.results.append(error_result)
                    self._append_result(error_result)

            # 최종 리포트
            all_results = self._load_all_results()
            self._generate_reports(all_results)

        finally:
            await self.shutdown()

    async def _process_item(
        self,
        item: BenchmarkItem,
        indexer: "BaseIndexer",
        retriever: Retriever,
    ) -> QuestionResult:
        """단일 질문 처리: index → retrieve → generate → evaluate → cleanup"""
        project_id = f"lme-{item.question_id}"

        try:
            # 1. INDEX
            num_indexed = await indexer.index(
                self.storage, item, project_id
            )
            logger.debug(
                f"{item.question_id}: indexed {num_indexed} chunks"
            )

            # 2. RETRIEVE
            results, retrieved_sids, metrics = await retriever.retrieve(
                query=item.question,
                project_id=project_id,
                answer_session_ids=item.answer_session_ids,
            )
            logger.debug(
                f"{item.question_id}: retrieved {len(results)} results, "
                f"recall_any@10={metrics.recall_any.get(10, 0):.2f}"
            )

            # 3. GENERATE
            hypothesis = await generate_answer(
                question=item.question,
                results=results,
                config=self.config.generation,
                question_date=item.question_date,
            )

            # 4. EVALUATE
            eval_label = await evaluate_answer(
                question=item.question,
                question_type=item.question_type,
                ground_truth=item.answer,
                hypothesis=hypothesis,
                config=self.config.evaluation,
            )

            return QuestionResult(
                question_id=item.question_id,
                question_type=item.question_type,
                question=item.question,
                answer=item.answer,
                hypothesis=hypothesis,
                retrieved_session_ids=retrieved_sids,
                retrieval_metrics=metrics,
                eval_label=eval_label,
            )

        finally:
            # 5. CLEANUP: project_id의 모든 메모리 삭제
            await self._cleanup_project(project_id)

    async def _cleanup_project(self, project_id: str) -> None:
        """project_id에 속한 모든 메모리 삭제"""
        if not self.storage:
            return

        try:
            from app.core.schemas.requests import SearchParams

            # 해당 project의 메모리 검색 후 삭제
            # 빈 쿼리로 project_id 필터링
            params = SearchParams(
                query="",
                project_id=project_id,
                limit=20,
            )
            while True:
                response = await self.storage.search_memories(params)
                if not response.results:
                    break
                for result in response.results:
                    await self.storage.delete_memory(result.id)
        except Exception as e:
            logger.warning(f"Cleanup failed for {project_id}: {e}")

    def _load_checkpoint(self) -> set:
        """체크포인트에서 완료된 question_id 집합 로드"""
        if not self.config.execution.resume_from_checkpoint:
            return set()

        path = Path(self._results_path)
        if not path.exists():
            return set()

        completed = set()
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    completed.add(data["question_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        return completed

    def _append_result(self, result: QuestionResult) -> None:
        """결과를 JSONL에 추가"""
        path = Path(self._results_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(result.model_dump_json() + "\n")

    def _load_all_results(self) -> List[QuestionResult]:
        """JSONL에서 모든 결과 로드"""
        path = Path(self._results_path)
        if not path.exists():
            return self.results

        results: List[QuestionResult] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(
                        QuestionResult.model_validate_json(line)
                    )
                except Exception:
                    continue
        return results

    def _generate_reports(
        self, results: List[QuestionResult]
    ) -> None:
        """최종 리포트 생성"""
        config_summary = {
            "model": self.config.generation.model,
            "judge": self.config.evaluation.judge_model,
            "top_k": str(self.config.retrieval.top_k),
            "search_mode": self.config.retrieval.search_mode,
        }

        report = generate_report(
            results=results,
            experiment_name=self.config.experiment_name,
            language=self.config.dataset.language,
            indexing_strategy=self.config.indexing.strategy,
            config_summary=config_summary,
        )

        # 콘솔 출력
        print_report(report)

        # 파일 저장
        results_dir = self.config.execution.results_dir
        lang = self.config.dataset.language
        strategy = self.config.indexing.strategy

        save_report_markdown(
            report,
            os.path.join(results_dir, f"{lang}_{strategy}_report.md"),
        )
        save_report_json(
            report,
            os.path.join(results_dir, f"{lang}_{strategy}_report.json"),
        )


async def run_evaluate_only(
    config: BenchmarkConfig,
    results_path: str,
) -> None:
    """JSONL 결과 파일에서 평가만 재실행"""
    path = Path(results_path)
    if not path.exists():
        raise FileNotFoundError(f"Results file not found: {results_path}")

    results: List[QuestionResult] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(
                    QuestionResult.model_validate_json(line)
                )
            except Exception:
                continue

    # 평가되지 않은 결과만 재평가
    for result in results:
        if result.eval_label is not None:
            continue
        if not result.hypothesis:
            continue

        label = await evaluate_answer(
            question=result.question,
            question_type=result.question_type,
            ground_truth=result.answer,
            hypothesis=result.hypothesis,
            config=config.evaluation,
        )
        result.eval_label = label

    # 결과 덮어쓰기
    with open(path, "w", encoding="utf-8") as f:
        for result in results:
            f.write(result.model_dump_json() + "\n")

    # 리포트
    report = generate_report(
        results=results,
        experiment_name=config.experiment_name,
        language=config.dataset.language,
        indexing_strategy=config.indexing.strategy,
    )
    print_report(report)


async def run_report_only(
    config: BenchmarkConfig,
    results_path: str,
) -> None:
    """JSONL 결과 파일에서 리포트만 생성"""
    path = Path(results_path)
    if not path.exists():
        raise FileNotFoundError(f"Results file not found: {results_path}")

    results: List[QuestionResult] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(
                    QuestionResult.model_validate_json(line)
                )
            except Exception:
                continue

    report = generate_report(
        results=results,
        experiment_name=config.experiment_name,
        language=config.dataset.language,
        indexing_strategy=config.indexing.strategy,
    )
    print_report(report)

    results_dir = config.execution.results_dir
    lang = config.dataset.language
    strategy = config.indexing.strategy

    save_report_markdown(
        report,
        os.path.join(results_dir, f"{lang}_{strategy}_report.md"),
    )
    save_report_json(
        report,
        os.path.join(results_dir, f"{lang}_{strategy}_report.json"),
    )
