#!/usr/bin/env python3
"""
임베딩 모델 벤치마크 스크립트

다양한 임베딩 모델의 성능을 비교 평가하여 최적의 모델을 선택합니다.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import matplotlib.pyplot as plt
import seaborn as sns

# 프로젝트 루트를 path에 추가
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.embeddings.service import EmbeddingService, MODEL_DIMENSIONS
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import SearchParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """벤치마크 결과 데이터 클래스"""
    model_name: str
    dimension: int
    embedding_time: float  # 임베딩 생성 시간 (초)
    search_time: float     # 검색 시간 (초)
    memory_usage: float    # 메모리 사용량 (MB)
    accuracy_scores: Dict[str, float]  # 정확도 점수들
    relevance_scores: List[float]      # 관련성 점수들


class EmbeddingModelBenchmark:
    """임베딩 모델 벤치마크 클래스"""
    
    # 테스트할 모델 목록 (성능 순)
    TEST_MODELS = [
        # 소형 모델 (빠른 속도)
        "all-MiniLM-L6-v2",
        "paraphrase-MiniLM-L6-v2", 
        "multi-qa-MiniLM-L6-cos-v1",
        "intfloat/multilingual-e5-small",
        
        # 중형 모델 (균형)
        "all-MiniLM-L12-v2",
        "distiluse-base-multilingual-cased-v2",
        "intfloat/multilingual-e5-base",
        
        # 대형 모델 (높은 정확도)
        "all-mpnet-base-v2",
        "multi-qa-mpnet-base-cos-v1",
        "intfloat/multilingual-e5-large",
    ]
    
    def __init__(self, db_path: str = "data/memories.db"):
        self.db_path = db_path
        self.storage = None
        self.test_queries = []
        self.ground_truth = {}
        self.results: List[BenchmarkResult] = []
    
    async def initialize(self):
        """벤치마크 초기화"""
        self.storage = DirectStorageBackend(self.db_path)
        await self.storage.initialize()
        
        # 테스트 쿼리 및 정답 데이터 준비
        await self._prepare_test_data()
    
    async def _prepare_test_data(self):
        """테스트 데이터 준비"""
        # 실제 메모리에서 다양한 쿼리 생성
        memories = await self.storage.get_all_memories(limit=100)
        
        if len(memories) < 10:
            logger.warning("메모리가 부족합니다. 더 많은 데이터로 테스트하는 것을 권장합니다.")
        
        # 다양한 유형의 테스트 쿼리 생성
        self.test_queries = [
            # 키워드 기반 쿼리
            "버그 수정",
            "성능 최적화", 
            "데이터베이스 설계",
            "API 구현",
            "테스트 작성",
            
            # 의미 기반 쿼리
            "코드 품질 개선 방법",
            "시스템 아키텍처 결정사항",
            "사용자 경험 향상",
            "보안 취약점 해결",
            "배포 자동화",
            
            # 복합 쿼리
            "프론트엔드 컴포넌트 리팩토링",
            "백엔드 API 에러 처리",
            "데이터베이스 마이그레이션 문제",
        ]
        
        # 각 쿼리에 대한 관련성 점수 기준 설정 (수동 또는 휴리스틱)
        for query in self.test_queries:
            self.ground_truth[query] = await self._get_relevance_baseline(query)
    
    async def _get_relevance_baseline(self, query: str) -> List[Tuple[str, float]]:
        """쿼리에 대한 관련성 기준선 생성"""
        # 간단한 키워드 매칭 기반 관련성 점수
        memories = await self.storage.get_all_memories(limit=50)
        relevance_scores = []
        
        query_lower = query.lower()
        for memory in memories:
            content_lower = memory.content.lower()
            
            # 키워드 매칭 점수 계산
            query_words = set(query_lower.split())
            content_words = set(content_lower.split())
            
            # Jaccard 유사도
            intersection = len(query_words & content_words)
            union = len(query_words | content_words)
            jaccard_score = intersection / union if union > 0 else 0
            
            # 카테고리 매칭 보너스
            category_bonus = 0.1 if any(word in content_lower for word in query_words) else 0
            
            final_score = jaccard_score + category_bonus
            relevance_scores.append((memory.id, final_score))
        
        # 점수 순으로 정렬
        relevance_scores.sort(key=lambda x: x[1], reverse=True)
        return relevance_scores[:10]  # 상위 10개만 반환
    
    async def benchmark_model(self, model_name: str) -> BenchmarkResult:
        """단일 모델 벤치마크"""
        logger.info(f"벤치마킹 시작: {model_name}")
        
        try:
            # 모델 로드 및 초기화
            start_time = time.time()
            embedding_service = EmbeddingService(model_name)
            load_time = time.time() - start_time
            
            # 메모리 사용량 측정 (근사치)
            import psutil
            process = psutil.Process()
            memory_before = process.memory_info().rss / 1024 / 1024  # MB
            
            # 임베딩 생성 시간 측정
            test_text = "이것은 임베딩 성능 테스트를 위한 샘플 텍스트입니다."
            
            start_time = time.time()
            for _ in range(10):  # 10회 평균
                embedding_service.embed(test_text)
            embedding_time = (time.time() - start_time) / 10
            
            memory_after = process.memory_info().rss / 1024 / 1024  # MB
            memory_usage = memory_after - memory_before
            
            # 검색 성능 측정
            search_times = []
            accuracy_scores = {}
            all_relevance_scores = []
            
            for query in self.test_queries:
                # 검색 시간 측정
                start_time = time.time()
                
                # 임시로 모델 변경하여 검색 수행
                original_service = self.storage.embedding_service
                self.storage.embedding_service = embedding_service
                
                try:
                    search_params = SearchParams(
                        query=query,
                        limit=10,
                        category=None,
                        project_id=None
                    )
                    search_result = await self.storage.search_memories(search_params)
                    results = search_result.results  # SearchResponse에서 results 추출
                    search_time = time.time() - start_time
                    search_times.append(search_time)
                    
                    # 정확도 계산
                    if query in self.ground_truth:
                        relevance_score = self._calculate_relevance_score(
                            results, self.ground_truth[query]
                        )
                        accuracy_scores[query] = relevance_score
                        all_relevance_scores.append(relevance_score)
                
                finally:
                    # 원래 서비스 복원
                    self.storage.embedding_service = original_service
            
            avg_search_time = np.mean(search_times) if search_times else 0
            
            result = BenchmarkResult(
                model_name=model_name,
                dimension=embedding_service.dimension,
                embedding_time=embedding_time,
                search_time=float(avg_search_time),
                memory_usage=memory_usage,
                accuracy_scores=accuracy_scores,
                relevance_scores=all_relevance_scores
            )
            
            logger.info(f"벤치마킹 완료: {model_name}")
            return result
            
        except Exception as e:
            logger.error(f"모델 {model_name} 벤치마킹 실패: {e}")
            return BenchmarkResult(
                model_name=model_name,
                dimension=0,
                embedding_time=float('inf'),
                search_time=float('inf'),
                memory_usage=0,
                accuracy_scores={},
                relevance_scores=[]
            )
    
    def _calculate_relevance_score(self, search_results, ground_truth) -> float:
        """검색 결과의 관련성 점수 계산"""
        if not search_results or not ground_truth:
            return 0.0
        
        # NDCG (Normalized Discounted Cumulative Gain) 계산
        ground_truth_dict = dict(ground_truth)
        
        dcg = 0.0
        for i, result in enumerate(search_results):
            relevance = ground_truth_dict.get(result.id, 0)
            dcg += relevance / np.log2(i + 2)  # i+2 because log2(1) = 0
        
        # Ideal DCG 계산
        ideal_relevances = sorted([score for _, score in ground_truth], reverse=True)
        idcg = sum(rel / np.log2(i + 2) for i, rel in enumerate(ideal_relevances))
        
        return dcg / idcg if idcg > 0 else 0.0
    
    async def run_benchmark(self, models: List[str] = None) -> List[BenchmarkResult]:
        """전체 벤치마크 실행"""
        if models is None:
            models = self.TEST_MODELS
        
        logger.info(f"벤치마크 시작: {len(models)}개 모델")
        
        for model_name in models:
            try:
                result = await self.benchmark_model(model_name)
                self.results.append(result)
            except Exception as e:
                logger.error(f"모델 {model_name} 벤치마크 실패: {e}")
        
        return self.results
    
    def generate_report(self, output_path: str = "benchmark_results.json"):
        """벤치마크 결과 보고서 생성"""
        if not self.results:
            logger.warning("벤치마크 결과가 없습니다.")
            return
        
        # JSON 보고서 생성
        report_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "test_queries": self.test_queries,
            "results": []
        }
        
        for result in self.results:
            report_data["results"].append({
                "model_name": result.model_name,
                "dimension": result.dimension,
                "embedding_time": result.embedding_time,
                "search_time": result.search_time,
                "memory_usage": result.memory_usage,
                "avg_relevance_score": np.mean(result.relevance_scores) if result.relevance_scores else 0,
                "accuracy_scores": result.accuracy_scores
            })
        
        # 결과 저장
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"벤치마크 보고서 저장: {output_path}")
        
        # 콘솔 요약 출력
        self._print_summary()
    
    def _print_summary(self):
        """벤치마크 결과 요약 출력"""
        print("\n" + "="*80)
        print("임베딩 모델 벤치마크 결과 요약")
        print("="*80)
        
        # 성능 순으로 정렬
        sorted_results = sorted(
            self.results, 
            key=lambda x: np.mean(x.relevance_scores) if x.relevance_scores else 0, 
            reverse=True
        )
        
        print(f"{'모델명':<35} {'차원':<6} {'임베딩시간':<10} {'검색시간':<10} {'메모리':<8} {'정확도':<8}")
        print("-" * 80)
        
        for result in sorted_results:
            avg_relevance = np.mean(result.relevance_scores) if result.relevance_scores else 0
            print(f"{result.model_name:<35} {result.dimension:<6} "
                  f"{result.embedding_time:.4f}s    {result.search_time:.4f}s    "
                  f"{result.memory_usage:.1f}MB   {avg_relevance:.3f}")
        
        # 추천 모델
        if sorted_results:
            best_model = sorted_results[0]
            print(f"\n🏆 추천 모델: {best_model.model_name}")
            print(f"   - 정확도: {np.mean(best_model.relevance_scores):.3f}")
            print(f"   - 임베딩 시간: {best_model.embedding_time:.4f}초")
            print(f"   - 검색 시간: {best_model.search_time:.4f}초")
    
    def create_visualization(self, output_dir: str = "benchmark_plots"):
        """벤치마크 결과 시각화"""
        if not self.results:
            return
        
        Path(output_dir).mkdir(exist_ok=True)
        
        # 데이터 준비
        models = [r.model_name for r in self.results]
        accuracies = [float(np.mean(r.relevance_scores)) if r.relevance_scores else 0.0 for r in self.results]
        embedding_times = [float(r.embedding_time) for r in self.results]
        search_times = [float(r.search_time) for r in self.results]
        memory_usages = [float(r.memory_usage) for r in self.results]
        
        # 1. 정확도 vs 속도 산점도
        plt.figure(figsize=(12, 8))
        plt.scatter(embedding_times, accuracies, s=100, alpha=0.7)
        
        for i, model in enumerate(models):
            plt.annotate(model.split('/')[-1], (embedding_times[i], accuracies[i]), 
                        xytext=(5, 5), textcoords='offset points', fontsize=8)
        
        plt.xlabel('임베딩 생성 시간 (초)')
        plt.ylabel('검색 정확도')
        plt.title('임베딩 모델 성능 비교: 정확도 vs 속도')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(f"{output_dir}/accuracy_vs_speed.png", dpi=300, bbox_inches='tight')
        plt.close()
        
        # 2. 종합 성능 히트맵
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        
        # 정확도
        axes[0,0].barh(models, accuracies)
        axes[0,0].set_title('검색 정확도')
        axes[0,0].set_xlabel('정확도 점수')
        
        # 임베딩 시간
        axes[0,1].barh(models, embedding_times)
        axes[0,1].set_title('임베딩 생성 시간')
        axes[0,1].set_xlabel('시간 (초)')
        
        # 검색 시간
        axes[1,0].barh(models, search_times)
        axes[1,0].set_title('검색 시간')
        axes[1,0].set_xlabel('시간 (초)')
        
        # 메모리 사용량
        axes[1,1].barh(models, memory_usages)
        axes[1,1].set_title('메모리 사용량')
        axes[1,1].set_xlabel('메모리 (MB)')
        
        plt.tight_layout()
        plt.savefig(f"{output_dir}/performance_comparison.png", dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"시각화 결과 저장: {output_dir}/")


async def main():
    """메인 실행 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="임베딩 모델 벤치마크")
    parser.add_argument("--db-path", default="data/memories.db", help="데이터베이스 경로")
    parser.add_argument("--models", nargs="+", help="테스트할 모델 목록")
    parser.add_argument("--output", default="benchmark_results.json", help="결과 파일 경로")
    parser.add_argument("--plot-dir", default="benchmark_plots", help="시각화 결과 디렉토리")
    
    args = parser.parse_args()
    
    benchmark = EmbeddingModelBenchmark(args.db_path)
    
    try:
        await benchmark.initialize()
        await benchmark.run_benchmark(args.models)
        benchmark.generate_report(args.output)
        benchmark.create_visualization(args.plot_dir)
        
    except Exception as e:
        logger.error(f"벤치마크 실행 실패: {e}")
        raise
    finally:
        if benchmark.storage:
            await benchmark.storage.shutdown()


if __name__ == "__main__":
    asyncio.run(main())