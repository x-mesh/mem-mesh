#!/usr/bin/env python3
"""
임베딩 모델 A/B 테스트 도구

두 개의 임베딩 모델을 실시간으로 비교하여 검색 품질을 평가합니다.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
import numpy as np

# 프로젝트 루트를 path에 추가
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.embeddings.service import EmbeddingService
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import SearchParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ABTestResult:
    """A/B 테스트 결과"""
    query: str
    model_a_results: List[Dict]
    model_b_results: List[Dict]
    model_a_time: float
    model_b_time: float
    user_preference: str  # 'A', 'B', 'tie', 'unknown'
    relevance_scores: Dict[str, float]


class EmbeddingABTest:
    """임베딩 모델 A/B 테스트 클래스"""
    
    def __init__(self, 
                 model_a: str, 
                 model_b: str, 
                 db_path: str = "data/memories.db"):
        self.model_a_name = model_a
        self.model_b_name = model_b
        self.db_path = db_path
        
        self.model_a_service = None
        self.model_b_service = None
        self.storage = None
        
        self.test_results: List[ABTestResult] = []
    
    async def initialize(self):
        """A/B 테스트 초기화"""
        logger.info(f"A/B 테스트 초기화: {self.model_a_name} vs {self.model_b_name}")
        
        # 모델 서비스 초기화
        self.model_a_service = EmbeddingService(self.model_a_name)
        self.model_b_service = EmbeddingService(self.model_b_name)
        
        # 스토리지 초기화
        self.storage = DirectStorageBackend(self.db_path)
        await self.storage.initialize()
        
        logger.info("A/B 테스트 초기화 완료")
    
    async def run_comparison(self, query: str, limit: int = 10) -> ABTestResult:
        """단일 쿼리에 대한 A/B 비교"""
        logger.info(f"쿼리 비교 실행: '{query}'")
        
        # 모델 A로 검색
        start_time = time.time()
        self.storage.embedding_service = self.model_a_service
        
        search_params = SearchParams(query=query, limit=limit)
        search_result_a = await self.storage.search_memories(search_params)
        results_a = search_result_a.results
        time_a = time.time() - start_time
        
        # 모델 B로 검색
        start_time = time.time()
        self.storage.embedding_service = self.model_b_service
        
        search_result_b = await self.storage.search_memories(search_params)
        results_b = search_result_b.results
        time_b = time.time() - start_time
        
        # 결과 변환
        results_a_dict = [
            {
                "id": r.id,
                "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                "category": r.category,
                "score": getattr(r, 'score', 0.0)
            }
            for r in results_a
        ]
        
        results_b_dict = [
            {
                "id": r.id,
                "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                "category": r.category,
                "score": getattr(r, 'score', 0.0)
            }
            for r in results_b
        ]
        
        result = ABTestResult(
            query=query,
            model_a_results=results_a_dict,
            model_b_results=results_b_dict,
            model_a_time=time_a,
            model_b_time=time_b,
            user_preference="unknown",
            relevance_scores={}
        )
        
        return result
    
    def display_comparison(self, result: ABTestResult):
        """비교 결과를 사용자에게 표시"""
        print("\n" + "="*80)
        print(f"쿼리: {result.query}")
        print("="*80)
        
        print(f"\n🅰️  모델 A ({self.model_a_name}) - 검색 시간: {result.model_a_time:.4f}초")
        print("-" * 40)
        for i, res in enumerate(result.model_a_results[:5], 1):
            print(f"{i}. [{res['category']}] {res['content']}")
            if 'score' in res:
                print(f"   점수: {res['score']:.3f}")
        
        print(f"\n🅱️  모델 B ({self.model_b_name}) - 검색 시간: {result.model_b_time:.4f}초")
        print("-" * 40)
        for i, res in enumerate(result.model_b_results[:5], 1):
            print(f"{i}. [{res['category']}] {res['content']}")
            if 'score' in res:
                print(f"   점수: {res['score']:.3f}")
    
    def get_user_feedback(self, result: ABTestResult) -> str:
        """사용자 피드백 수집"""
        print(f"\n어떤 결과가 더 관련성이 높나요?")
        print("A: 모델 A 결과가 더 좋음")
        print("B: 모델 B 결과가 더 좋음") 
        print("T: 비슷함 (Tie)")
        print("S: 건너뛰기")
        
        while True:
            choice = input("선택 (A/B/T/S): ").upper().strip()
            if choice in ['A', 'B', 'T', 'S']:
                if choice == 'S':
                    return 'unknown'
                elif choice == 'T':
                    return 'tie'
                else:
                    return choice
            print("올바른 선택지를 입력해주세요 (A/B/T/S)")
    
    async def run_interactive_test(self, queries: List[str] = None):
        """대화형 A/B 테스트 실행"""
        if queries is None:
            queries = [
                "버그 수정 방법",
                "성능 최적화",
                "데이터베이스 설계",
                "API 구현",
                "테스트 작성",
                "코드 리뷰",
                "배포 자동화",
                "보안 취약점",
                "사용자 인터페이스",
                "시스템 아키텍처"
            ]
        
        print(f"\n🔬 임베딩 모델 A/B 테스트")
        print(f"모델 A: {self.model_a_name}")
        print(f"모델 B: {self.model_b_name}")
        print(f"테스트 쿼리 수: {len(queries)}")
        
        for i, query in enumerate(queries, 1):
            print(f"\n진행률: {i}/{len(queries)}")
            
            # 비교 실행
            result = await self.run_comparison(query)
            
            # 결과 표시
            self.display_comparison(result)
            
            # 사용자 피드백 수집
            preference = self.get_user_feedback(result)
            result.user_preference = preference
            
            # 결과 저장
            self.test_results.append(result)
            
            if preference == 'unknown':
                continue
        
        # 최종 결과 분석
        self.analyze_results()
    
    def analyze_results(self):
        """A/B 테스트 결과 분석"""
        if not self.test_results:
            print("분석할 결과가 없습니다.")
            return
        
        # 선호도 집계
        preferences = [r.user_preference for r in self.test_results if r.user_preference != 'unknown']
        
        if not preferences:
            print("사용자 피드백이 없습니다.")
            return
        
        a_wins = preferences.count('A')
        b_wins = preferences.count('B')
        ties = preferences.count('tie')
        total = len(preferences)
        
        print("\n" + "="*60)
        print("A/B 테스트 결과 분석")
        print("="*60)
        
        print(f"총 평가 수: {total}")
        print(f"모델 A ({self.model_a_name}) 승리: {a_wins} ({a_wins/total*100:.1f}%)")
        print(f"모델 B ({self.model_b_name}) 승리: {b_wins} ({b_wins/total*100:.1f}%)")
        print(f"무승부: {ties} ({ties/total*100:.1f}%)")
        
        # 성능 비교
        avg_time_a = np.mean([r.model_a_time for r in self.test_results])
        avg_time_b = np.mean([r.model_b_time for r in self.test_results])
        
        print(f"\n평균 검색 시간:")
        print(f"모델 A: {avg_time_a:.4f}초")
        print(f"모델 B: {avg_time_b:.4f}초")
        
        # 추천
        if a_wins > b_wins:
            winner = f"모델 A ({self.model_a_name})"
            win_rate = a_wins / total * 100
        elif b_wins > a_wins:
            winner = f"모델 B ({self.model_b_name})"
            win_rate = b_wins / total * 100
        else:
            winner = "무승부"
            win_rate = 50.0
        
        print(f"\n🏆 추천: {winner}")
        if winner != "무승부":
            print(f"승률: {win_rate:.1f}%")
        
        # 통계적 유의성 (간단한 이항 검정)
        if total >= 10:
            from scipy import stats
            # 귀무가설: 두 모델의 성능이 같다 (p=0.5)
            if a_wins + b_wins > 0:
                p_value = stats.binom_test(max(a_wins, b_wins), a_wins + b_wins, 0.5)
                print(f"통계적 유의성 (p-value): {p_value:.4f}")
                if p_value < 0.05:
                    print("✅ 통계적으로 유의한 차이가 있습니다 (p < 0.05)")
                else:
                    print("❌ 통계적으로 유의한 차이가 없습니다 (p >= 0.05)")
    
    def save_results(self, output_path: str = "ab_test_results.json"):
        """결과를 JSON 파일로 저장"""
        results_data = {
            "model_a": self.model_a_name,
            "model_b": self.model_b_name,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_tests": len(self.test_results),
            "results": []
        }
        
        for result in self.test_results:
            results_data["results"].append({
                "query": result.query,
                "model_a_time": result.model_a_time,
                "model_b_time": result.model_b_time,
                "user_preference": result.user_preference,
                "model_a_results_count": len(result.model_a_results),
                "model_b_results_count": len(result.model_b_results)
            })
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"A/B 테스트 결과 저장: {output_path}")
    
    async def shutdown(self):
        """리소스 정리"""
        if self.storage:
            await self.storage.shutdown()


async def main():
    """메인 실행 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="임베딩 모델 A/B 테스트")
    parser.add_argument("model_a", help="모델 A 이름")
    parser.add_argument("model_b", help="모델 B 이름")
    parser.add_argument("--db-path", default="data/memories.db", help="데이터베이스 경로")
    parser.add_argument("--queries", nargs="+", help="테스트 쿼리 목록")
    parser.add_argument("--output", default="ab_test_results.json", help="결과 파일 경로")
    
    args = parser.parse_args()
    
    ab_test = EmbeddingABTest(args.model_a, args.model_b, args.db_path)
    
    try:
        await ab_test.initialize()
        await ab_test.run_interactive_test(args.queries)
        ab_test.save_results(args.output)
        
    except KeyboardInterrupt:
        print("\n테스트가 중단되었습니다.")
        ab_test.analyze_results()
        ab_test.save_results(args.output)
    except Exception as e:
        logger.error(f"A/B 테스트 실행 실패: {e}")
        raise
    finally:
        await ab_test.shutdown()


if __name__ == "__main__":
    asyncio.run(main())