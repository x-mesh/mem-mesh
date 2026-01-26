#!/usr/bin/env python3
"""
벡터 DB 비교 벤치마크

SQLite-vec vs PostgreSQL (pgvector) vs Qdrant 성능 및 품질 비교
"""

import asyncio
import time
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.config import Settings


@dataclass
class BenchmarkQuery:
    """벤치마크 쿼리"""
    id: str
    query: str
    expected_results: List[str]  # 예상되는 메모리 ID 목록
    description: str


@dataclass
class SearchResult:
    """검색 결과"""
    memory_id: str
    similarity_score: float
    content: str


@dataclass
class BenchmarkResult:
    """벤치마크 결과"""
    db_type: str
    query_id: str
    query: str
    
    # 검색 품질
    precision_at_5: float
    recall_at_5: float
    mrr: float  # Mean Reciprocal Rank
    
    # 성능
    query_time_ms: float
    
    # 결과
    results: List[Dict[str, Any]]


class VectorDBBenchmark:
    """벡터 DB 벤치마크"""
    
    def __init__(self):
        self.settings = Settings()
        self.embedding_service = EmbeddingService(self.settings)
        
    async def setup(self):
        """초기화"""
        await self.embedding_service.initialize()
    
    async def cleanup(self):
        """정리"""
        await self.embedding_service.cleanup()
    
    def get_benchmark_queries(self) -> List[BenchmarkQuery]:
        """벤치마크 쿼리 세트 정의"""
        return [
            BenchmarkQuery(
                id="q1",
                query="MCP 설정 방법",
                expected_results=[],  # 실제 데이터 분석 후 채움
                description="MCP 설정 관련 쿼리"
            ),
            BenchmarkQuery(
                id="q2",
                query="데이터베이스 마이그레이션",
                expected_results=[],
                description="DB 마이그레이션 관련 쿼리"
            ),
            BenchmarkQuery(
                id="q3",
                query="검색 품질 개선",
                expected_results=[],
                description="검색 품질 관련 쿼리"
            ),
            BenchmarkQuery(
                id="q4",
                query="서버 실행 모드",
                expected_results=[],
                description="서버 설정 관련 쿼리"
            ),
            BenchmarkQuery(
                id="q5",
                query="벡터 임베딩 모델",
                expected_results=[],
                description="임베딩 모델 관련 쿼리"
            ),
        ]
    
    async def benchmark_sqlite(
        self, 
        queries: List[BenchmarkQuery]
    ) -> List[BenchmarkResult]:
        """SQLite-vec 벤치마크"""
        print("\n" + "="*60)
        print("  SQLite-vec 벤치마크")
        print("="*60)
        
        db = Database(self.settings.database_path)
        await db.connect()
        
        results = []
        
        try:
            for query in queries:
                print(f"\n쿼리: {query.query}")
                
                # 임베딩 생성
                query_embedding = await self.embedding_service.generate_embedding(
                    query.query
                )
                
                # 검색 실행 (시간 측정)
                start_time = time.time()
                
                rows = await db.fetchall(
                    """
                    SELECT 
                        m.id,
                        m.content,
                        vec_distance_cosine(me.embedding, ?) as distance
                    FROM memories m
                    JOIN memory_embeddings me ON m.id = me.memory_id
                    WHERE m.project_id = 'mem-mesh'
                    ORDER BY distance ASC
                    LIMIT 5
                    """,
                    (query_embedding.tobytes(),)
                )
                
                query_time = (time.time() - start_time) * 1000
                
                # 결과 변환
                search_results = [
                    {
                        "id": row["id"],
                        "content": row["content"][:100],
                        "similarity": 1 - row["distance"]
                    }
                    for row in rows
                ]
                
                # 품질 지표 계산
                precision, recall, mrr = self._calculate_metrics(
                    search_results,
                    query.expected_results
                )
                
                result = BenchmarkResult(
                    db_type="sqlite-vec",
                    query_id=query.id,
                    query=query.query,
                    precision_at_5=precision,
                    recall_at_5=recall,
                    mrr=mrr,
                    query_time_ms=query_time,
                    results=search_results
                )
                
                results.append(result)
                
                print(f"  시간: {query_time:.2f}ms")
                print(f"  결과: {len(search_results)}개")
                
        finally:
            await db.close()
        
        return results
    
    async def benchmark_postgres(
        self, 
        queries: List[BenchmarkQuery]
    ) -> List[BenchmarkResult]:
        """PostgreSQL (pgvector) 벤치마크"""
        print("\n" + "="*60)
        print("  PostgreSQL (pgvector) 벤치마크")
        print("="*60)
        print("  ⚠️  구현 필요: PostgreSQL 연결 및 쿼리")
        
        # TODO: PostgreSQL 구현
        return []
    
    async def benchmark_qdrant(
        self, 
        queries: List[BenchmarkQuery]
    ) -> List[BenchmarkResult]:
        """Qdrant 벤치마크"""
        print("\n" + "="*60)
        print("  Qdrant 벤치마크")
        print("="*60)
        print("  ⚠️  구현 필요: Qdrant 연결 및 쿼리")
        
        # TODO: Qdrant 구현
        return []
    
    def _calculate_metrics(
        self,
        results: List[Dict[str, Any]],
        expected: List[str]
    ) -> Tuple[float, float, float]:
        """검색 품질 지표 계산"""
        if not expected:
            # Ground truth가 없으면 계산 불가
            return 0.0, 0.0, 0.0
        
        result_ids = [r["id"] for r in results]
        
        # Precision@5
        relevant_count = sum(1 for rid in result_ids if rid in expected)
        precision = relevant_count / len(result_ids) if result_ids else 0.0
        
        # Recall@5
        recall = relevant_count / len(expected) if expected else 0.0
        
        # MRR (Mean Reciprocal Rank)
        mrr = 0.0
        for i, rid in enumerate(result_ids, 1):
            if rid in expected:
                mrr = 1.0 / i
                break
        
        return precision, recall, mrr
    
    def print_summary(self, all_results: Dict[str, List[BenchmarkResult]]):
        """결과 요약 출력"""
        print("\n" + "="*60)
        print("  벤치마크 결과 요약")
        print("="*60)
        
        for db_type, results in all_results.items():
            if not results:
                continue
            
            print(f"\n{db_type}:")
            print("-" * 60)
            
            # 평균 계산
            avg_precision = sum(r.precision_at_5 for r in results) / len(results)
            avg_recall = sum(r.recall_at_5 for r in results) / len(results)
            avg_mrr = sum(r.mrr for r in results) / len(results)
            avg_time = sum(r.query_time_ms for r in results) / len(results)
            
            print(f"  평균 Precision@5: {avg_precision:.3f}")
            print(f"  평균 Recall@5:    {avg_recall:.3f}")
            print(f"  평균 MRR:         {avg_mrr:.3f}")
            print(f"  평균 쿼리 시간:   {avg_time:.2f}ms")
    
    def save_results(
        self, 
        all_results: Dict[str, List[BenchmarkResult]], 
        output_file: str
    ):
        """결과를 JSON 파일로 저장"""
        output = {
            db_type: [asdict(r) for r in results]
            for db_type, results in all_results.items()
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"\n결과 저장: {output_file}")


async def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="벡터 DB 벤치마크")
    parser.add_argument(
        "--dbs",
        nargs="+",
        choices=["sqlite", "postgres", "qdrant", "all"],
        default=["sqlite"],
        help="테스트할 DB 선택"
    )
    parser.add_argument(
        "--output",
        default="benchmark_results.json",
        help="결과 저장 파일"
    )
    args = parser.parse_args()
    
    benchmark = VectorDBBenchmark()
    await benchmark.setup()
    
    try:
        queries = benchmark.get_benchmark_queries()
        all_results = {}
        
        dbs_to_test = args.dbs
        if "all" in dbs_to_test:
            dbs_to_test = ["sqlite", "postgres", "qdrant"]
        
        # SQLite 벤치마크
        if "sqlite" in dbs_to_test:
            all_results["sqlite-vec"] = await benchmark.benchmark_sqlite(queries)
        
        # PostgreSQL 벤치마크
        if "postgres" in dbs_to_test:
            all_results["postgresql"] = await benchmark.benchmark_postgres(queries)
        
        # Qdrant 벤치마크
        if "qdrant" in dbs_to_test:
            all_results["qdrant"] = await benchmark.benchmark_qdrant(queries)
        
        # 결과 출력 및 저장
        benchmark.print_summary(all_results)
        benchmark.save_results(all_results, args.output)
        
    finally:
        await benchmark.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
