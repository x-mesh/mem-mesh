#!/usr/bin/env python3
"""
검색 품질 평가 도구

다양한 메트릭을 사용하여 임베딩 기반 검색의 품질을 정량적으로 평가합니다.
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

# 프로젝트 루트를 path에 추가
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.embeddings.service import EmbeddingService
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import SearchParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SearchQualityMetrics:
    """검색 품질 메트릭"""
    precision_at_k: Dict[int, float]  # P@K
    recall_at_k: Dict[int, float]     # R@K
    ndcg_at_k: Dict[int, float]       # NDCG@K
    mrr: float                        # Mean Reciprocal Rank
    map_score: float                  # Mean Average Precision
    diversity_score: float            # 결과 다양성
    coverage_score: float             # 카테고리 커버리지


class SearchQualityEvaluator:
    """검색 품질 평가 클래스"""
    
    def __init__(self, db_path: str = "data/memories.db"):
        self.db_path = db_path
        self.storage = None
        self.test_queries = []
        self.ground_truth = {}
    
    async def initialize(self):
        """평가기 초기화"""
        self.storage = DirectStorageBackend(self.db_path)
        await self.storage.initialize()
        
        # 테스트 데이터 준비
        await self._prepare_evaluation_data()
    
    async def _prepare_evaluation_data(self):
        """평가 데이터 준비"""
        # 실제 메모리에서 테스트 쿼리 생성
        memories = await self.storage.get_all_memories(limit=200)
        
        if len(memories) < 20:
            logger.warning("평가를 위한 충분한 데이터가 없습니다. 최소 20개의 메모리가 필요합니다.")
        
        # 다양한 유형의 테스트 쿼리 생성
        self.test_queries = [
            # 정확한 키워드 매칭
            "버그", "에러", "수정", "구현", "테스트",
            
            # 의미적 쿼리
            "문제 해결", "성능 개선", "코드 품질", "사용자 경험",
            
            # 복합 쿼리
            "데이터베이스 연결 오류", "API 응답 시간 최적화",
            "프론트엔드 컴포넌트 리팩토링", "백엔드 보안 강화",
            
            # 카테고리별 쿼리
            "결정사항", "아이디어", "작업 완료", "코드 스니펫"
        ]
        
        # 각 쿼리에 대한 관련성 기준 생성
        for query in self.test_queries:
            self.ground_truth[query] = await self._create_relevance_labels(query, memories)
    
    async def _create_relevance_labels(self, query: str, memories: List) -> Dict[str, int]:
        """쿼리에 대한 관련성 라벨 생성 (0: 무관련, 1: 관련, 2: 매우 관련)"""
        relevance_labels = {}
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for memory in memories:
            content_lower = memory.content.lower()
            content_words = set(content_lower.split())
            
            # 관련성 점수 계산
            score = 0
            
            # 1. 키워드 매칭
            common_words = query_words & content_words
            if common_words:
                score += len(common_words) / len(query_words)
            
            # 2. 부분 문자열 매칭
            if query_lower in content_lower:
                score += 1.0
            
            # 3. 카테고리 매칭
            if any(word in memory.category.lower() for word in query_words):
                score += 0.5
            
            # 4. 태그 매칭 (있는 경우)
            if hasattr(memory, 'tags') and memory.tags:
                tag_words = set(' '.join(memory.tags).lower().split())
                if query_words & tag_words:
                    score += 0.3
            
            # 점수를 0-2 범위로 정규화
            if score >= 1.5:
                relevance_labels[memory.id] = 2  # 매우 관련
            elif score >= 0.5:
                relevance_labels[memory.id] = 1  # 관련
            else:
                relevance_labels[memory.id] = 0  # 무관련
        
        return relevance_labels
    
    async def evaluate_search_quality(self, 
                                    model_name: str = None,
                                    k_values: List[int] = None) -> SearchQualityMetrics:
        """검색 품질 평가 실행"""
        if k_values is None:
            k_values = [1, 3, 5, 10]
        
        if model_name:
            # 특정 모델로 평가
            embedding_service = EmbeddingService(model_name)
            original_service = self.storage.embedding_service
            self.storage.embedding_service = embedding_service
        
        try:
            all_precisions = {k: [] for k in k_values}
            all_recalls = {k: [] for k in k_values}
            all_ndcgs = {k: [] for k in k_values}
            all_rrs = []
            all_aps = []
            
            category_coverage = set()
            all_diversities = []
            
            for query in self.test_queries:
                if query not in self.ground_truth:
                    continue
                
                # 검색 실행
                search_params = SearchParams(query=query, limit=max(k_values))
                search_result = await self.storage.search_memories(search_params)
                results = search_result.results
                
                if not results:
                    continue
                
                # 관련성 라벨 가져오기
                relevance_labels = self.ground_truth[query]
                
                # 결과의 관련성 점수 추출
                result_relevances = []
                for result in results:
                    relevance = relevance_labels.get(result.id, 0)
                    result_relevances.append(relevance)
                
                # 메트릭 계산
                for k in k_values:
                    if len(results) >= k:
                        # Precision@K
                        precision_k = self._calculate_precision_at_k(result_relevances[:k])
                        all_precisions[k].append(precision_k)
                        
                        # Recall@K
                        recall_k = self._calculate_recall_at_k(
                            result_relevances[:k], relevance_labels
                        )
                        all_recalls[k].append(recall_k)
                        
                        # NDCG@K
                        ndcg_k = self._calculate_ndcg_at_k(result_relevances[:k])
                        all_ndcgs[k].append(ndcg_k)
                
                # MRR (Mean Reciprocal Rank)
                rr = self._calculate_reciprocal_rank(result_relevances)
                if rr > 0:
                    all_rrs.append(rr)
                
                # MAP (Mean Average Precision)
                ap = self._calculate_average_precision(result_relevances, relevance_labels)
                all_aps.append(ap)
                
                # 다양성 점수
                diversity = self._calculate_diversity(results)
                all_diversities.append(diversity)
                
                # 카테고리 커버리지
                for result in results:
                    category_coverage.add(result.category)
            
            # 전체 메트릭 계산
            precision_at_k = {k: float(np.mean(all_precisions[k])) if all_precisions[k] else 0.0 
                             for k in k_values}
            recall_at_k = {k: float(np.mean(all_recalls[k])) if all_recalls[k] else 0.0 
                          for k in k_values}
            ndcg_at_k = {k: float(np.mean(all_ndcgs[k])) if all_ndcgs[k] else 0.0 
                        for k in k_values}
            
            mrr = float(np.mean(all_rrs)) if all_rrs else 0.0
            map_score = float(np.mean(all_aps)) if all_aps else 0.0
            diversity_score = float(np.mean(all_diversities)) if all_diversities else 0.0
            
            # 카테고리 커버리지 (전체 카테고리 대비 비율)
            all_categories = set()
            all_memories = await self.storage.get_all_memories(limit=1000)
            for memory in all_memories:
                all_categories.add(memory.category)
            
            coverage_score = float(len(category_coverage) / len(all_categories)) if all_categories else 0.0
            
            return SearchQualityMetrics(
                precision_at_k=precision_at_k,
                recall_at_k=recall_at_k,
                ndcg_at_k=ndcg_at_k,
                mrr=mrr,
                map_score=map_score,
                diversity_score=diversity_score,
                coverage_score=coverage_score
            )
        
        finally:
            if model_name:
                # 원래 서비스 복원
                self.storage.embedding_service = original_service
    
    def _calculate_precision_at_k(self, relevances: List[int]) -> float:
        """Precision@K 계산"""
        if not relevances:
            return 0.0
        return sum(1 for r in relevances if r > 0) / len(relevances)
    
    def _calculate_recall_at_k(self, relevances: List[int], all_relevances: Dict[str, int]) -> float:
        """Recall@K 계산"""
        relevant_items = sum(1 for r in all_relevances.values() if r > 0)
        if relevant_items == 0:
            return 0.0
        
        retrieved_relevant = sum(1 for r in relevances if r > 0)
        return retrieved_relevant / relevant_items
    
    def _calculate_ndcg_at_k(self, relevances: List[int]) -> float:
        """NDCG@K 계산"""
        if not relevances:
            return 0.0
        
        # DCG 계산
        dcg = relevances[0]
        for i in range(1, len(relevances)):
            dcg += relevances[i] / np.log2(i + 1)
        
        # IDCG 계산 (이상적인 순서)
        ideal_relevances = sorted(relevances, reverse=True)
        idcg = ideal_relevances[0] if ideal_relevances else 0
        for i in range(1, len(ideal_relevances)):
            idcg += ideal_relevances[i] / np.log2(i + 1)
        
        return dcg / idcg if idcg > 0 else 0.0
    
    def _calculate_reciprocal_rank(self, relevances: List[int]) -> float:
        """Reciprocal Rank 계산"""
        for i, relevance in enumerate(relevances):
            if relevance > 0:
                return 1.0 / (i + 1)
        return 0.0
    
    def _calculate_average_precision(self, relevances: List[int], all_relevances: Dict[str, int]) -> float:
        """Average Precision 계산"""
        relevant_items = sum(1 for r in all_relevances.values() if r > 0)
        if relevant_items == 0:
            return 0.0
        
        precision_sum = 0.0
        relevant_count = 0
        
        for i, relevance in enumerate(relevances):
            if relevance > 0:
                relevant_count += 1
                precision_at_i = relevant_count / (i + 1)
                precision_sum += precision_at_i
        
        return precision_sum / relevant_items
    
    def _calculate_diversity(self, results: List) -> float:
        """결과 다양성 계산 (카테고리 기반)"""
        if not results:
            return 0.0
        
        categories = set(result.category for result in results)
        return len(categories) / len(results)
    
    async def compare_models(self, models: List[str]) -> Dict[str, SearchQualityMetrics]:
        """여러 모델의 검색 품질 비교"""
        results = {}
        
        for model_name in models:
            logger.info(f"모델 평가 중: {model_name}")
            try:
                metrics = await self.evaluate_search_quality(model_name)
                results[model_name] = metrics
            except Exception as e:
                logger.error(f"모델 {model_name} 평가 실패: {e}")
        
        return results
    
    def print_evaluation_report(self, 
                              results: Dict[str, SearchQualityMetrics],
                              output_file: str = None):
        """평가 결과 보고서 출력"""
        report_lines = []
        
        report_lines.append("=" * 80)
        report_lines.append("검색 품질 평가 보고서")
        report_lines.append("=" * 80)
        
        if not results:
            report_lines.append("평가 결과가 없습니다.")
            return
        
        # 헤더
        header = f"{'모델명':<35} {'P@5':<8} {'R@5':<8} {'NDCG@5':<8} {'MRR':<8} {'MAP':<8} {'다양성':<8}"
        report_lines.append(header)
        report_lines.append("-" * 80)
        
        # 결과 정렬 (NDCG@5 기준)
        sorted_results = sorted(
            results.items(),
            key=lambda x: x[1].ndcg_at_k.get(5, 0),
            reverse=True
        )
        
        for model_name, metrics in sorted_results:
            line = (f"{model_name:<35} "
                   f"{metrics.precision_at_k.get(5, 0):.3f}    "
                   f"{metrics.recall_at_k.get(5, 0):.3f}    "
                   f"{metrics.ndcg_at_k.get(5, 0):.3f}    "
                   f"{metrics.mrr:.3f}    "
                   f"{metrics.map_score:.3f}    "
                   f"{metrics.diversity_score:.3f}")
            report_lines.append(line)
        
        # 상세 메트릭
        report_lines.append("\n상세 메트릭:")
        report_lines.append("-" * 40)
        
        for model_name, metrics in sorted_results:
            report_lines.append(f"\n🔍 {model_name}")
            report_lines.append(f"  Precision@K: {metrics.precision_at_k}")
            report_lines.append(f"  Recall@K: {metrics.recall_at_k}")
            report_lines.append(f"  NDCG@K: {metrics.ndcg_at_k}")
            report_lines.append(f"  MRR: {metrics.mrr:.4f}")
            report_lines.append(f"  MAP: {metrics.map_score:.4f}")
            report_lines.append(f"  다양성: {metrics.diversity_score:.4f}")
            report_lines.append(f"  커버리지: {metrics.coverage_score:.4f}")
        
        # 추천
        if sorted_results:
            best_model, best_metrics = sorted_results[0]
            report_lines.append(f"\n🏆 추천 모델: {best_model}")
            report_lines.append(f"   NDCG@5: {best_metrics.ndcg_at_k.get(5, 0):.3f}")
            report_lines.append(f"   MRR: {best_metrics.mrr:.3f}")
        
        # 출력
        report_text = "\n".join(report_lines)
        print(report_text)
        
        # 파일 저장
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_text)
            logger.info(f"평가 보고서 저장: {output_file}")
    
    async def shutdown(self):
        """리소스 정리"""
        if self.storage:
            await self.storage.shutdown()


async def main():
    """메인 실행 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="검색 품질 평가 도구")
    parser.add_argument("--models", nargs="+", help="평가할 모델 목록")
    parser.add_argument("--db-path", default="data/memories.db", help="데이터베이스 경로")
    parser.add_argument("--output", help="결과 파일 경로")
    
    args = parser.parse_args()
    
    evaluator = SearchQualityEvaluator(args.db_path)
    
    try:
        await evaluator.initialize()
        
        if args.models:
            # 여러 모델 비교
            results = await evaluator.compare_models(args.models)
        else:
            # 현재 모델만 평가
            current_metrics = await evaluator.evaluate_search_quality()
            results = {"current_model": current_metrics}
        
        evaluator.print_evaluation_report(results, args.output)
        
    except Exception as e:
        logger.error(f"평가 실행 실패: {e}")
        raise
    finally:
        await evaluator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())