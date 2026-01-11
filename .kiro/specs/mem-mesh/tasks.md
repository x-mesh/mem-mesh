# Implementation Plan: mem-mesh

## Overview

mem-mesh 중앙 메모리 서버를 Python(FastAPI + MCP)으로 구현합니다. SQLite + sqlite-vec를 사용하여 메타데이터와 벡터를 단일 파일에 저장하고, sentence-transformers로 로컬 임베딩을 생성합니다.

## Tasks

- [x] 1. 프로젝트 초기화 및 기본 구조 설정
  - [x] 1.1 프로젝트 디렉토리 구조 생성 및 pyproject.toml 설정
    - src/, tests/ 디렉토리 생성
    - Poetry 또는 pip 의존성 설정 (fastapi, uvicorn, sentence-transformers, sqlite-vec, pydantic, mcp)
    - _Requirements: 6.1_
  - [x] 1.2 설정 모듈 구현 (src/config.py)
    - pydantic-settings 기반 Settings 클래스
    - .env 파일 로드 및 환경 변수 처리
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_
  - [x] 1.3 로깅 모듈 구현 (src/utils/logger.py)
    - 구조화된 JSON 로깅 설정
    - LOG_LEVEL 기반 로그 레벨 설정
    - _Requirements: 9.2, 9.3, 9.6_

- [x] 2. 데이터베이스 레이어 구현
  - [x] 2.1 데이터베이스 연결 및 초기화 (src/database/base.py)
    - SQLite 연결 관리
    - sqlite-vec 확장 로드
    - 테이블 및 인덱스 자동 생성
    - _Requirements: 6.9, 6.10, 8.5, 8.6_
  - [x] 2.2 Memory 모델 정의 (src/database/models.py)
    - SQLModel 기반 Memory 클래스
    - 모든 필드 정의 (id, content, content_hash, project_id, category, source, embedding, tags, created_at, updated_at)
    - _Requirements: 8.1_
  - [x] 2.3 Pydantic 스키마 정의 (src/schemas/)
    - AddParams, AddResponse
    - SearchParams, SearchResult, SearchResponse
    - ContextParams, RelatedMemory, ContextResponse
    - DeleteParams, DeleteResponse
    - UpdateParams, UpdateResponse
    - ErrorResponse
    - _Requirements: 1.6, 2.10, 3.7, 4.3, 5.4, 9.1_
  - [ ]* 2.4 Property test: Memory 직렬화 round-trip
    - **Property 15: Memory Serialization Round-Trip**
    - **Validates: Requirements 8.7**

- [x] 3. Embedding 서비스 구현
  - [x] 3.1 EmbeddingService 클래스 구현 (src/embeddings/service.py)
    - sentence-transformers 모델 로드 (lazy loading)
    - embed() 메서드: 단일 텍스트 → 384dim 벡터
    - to_bytes() / from_bytes() 메서드: 벡터 ↔ bytes 변환
    - _Requirements: 1.1, 2.1, 6.4, 6.5, 6.11_
  - [ ]* 3.2 Property test: Embedding 차원 일관성
    - **Property 1: Embedding Dimension Consistency**
    - **Validates: Requirements 1.1, 2.1, 8.4**

- [x] 4. Memory 서비스 구현
  - [x] 4.1 MemoryService 클래스 구현 (src/services/memory.py)
    - create(): 메모리 생성 (content_hash 중복 감지 포함)
    - get(): ID로 메모리 조회
    - update(): 메모리 업데이트 (content 변경 시 재임베딩)
    - delete(): 메모리 삭제 (SQLite + 벡터 인덱스)
    - _Requirements: 1.1-1.10, 4.1-4.5, 5.1-5.5_
  - [ ]* 4.2 Property test: Content 길이 검증
    - **Property 2: Content Length Validation**
    - **Validates: Requirements 1.4, 1.5**
  - [ ]* 4.3 Property test: 중복 감지
    - **Property 4: Duplicate Detection via Content Hash**
    - **Validates: Requirements 1.7**
  - [ ]* 4.4 Property test: 저장 응답 완전성
    - **Property 3: Memory Save Response Completeness**
    - **Validates: Requirements 1.6**
  - [ ]* 4.5 Property test: 저장 round-trip
    - **Property 5: Memory Persistence Round-Trip**
    - **Validates: Requirements 1.10**
  - [ ]* 4.6 Property test: Content hash 계산
    - **Property 16: Content Hash Computation**
    - **Validates: Requirements 8.3**
  - [ ]* 4.7 Property test: UUID 생성
    - **Property 17: UUID Generation**
    - **Validates: Requirements 8.2**

- [x] 5. Checkpoint - 기본 저장/조회 기능 검증
  - 모든 테스트 통과 확인
  - 메모리 저장 및 ID로 조회 동작 확인
  - 질문이 있으면 사용자에게 문의

- [-] 6. Search 서비스 구현
  - [x] 6.1 SearchService 클래스 구현 (src/services/search.py)
    - search(): 하이브리드 검색 (SQL 필터 + 벡터 유사도)
    - _calculate_recency_score(): 최신성 점수 계산
    - recency_weight 적용: score = (1-α)*sim + α*recency
    - _Requirements: 2.1-2.11_
  - [ ]* 6.2 Property test: 검색 필터 정확성
    - **Property 6: Search Filter Correctness**
    - **Validates: Requirements 2.3, 2.4**
  - [ ]* 6.3 Property test: 검색 결과 필드 완전성
    - **Property 7: Search Results Field Completeness**
    - **Validates: Requirements 2.10**
  - [ ]* 6.4 Property test: 유사도 임계값
    - **Property 8: Search Similarity Threshold**
    - **Validates: Requirements 2.5**
  - [ ]* 6.5 Property test: 검색 limit 적용
    - **Property 9: Search Limit Enforcement**
    - **Validates: Requirements 2.8**
  - [ ]* 6.6 Property test: Recency weight 공식
    - **Property 10: Recency Weight Scoring**
    - **Validates: Requirements 2.6**

- [x] 7. Context 서비스 구현
  - [x] 7.1 ContextService 클래스 구현 (src/services/context.py)
    - get_context(): 맥락 조회 (primary + related + timeline)
    - _classify_relationship(): 관계 분류 (before/after/similar)
    - depth 기반 확장 검색
    - _Requirements: 3.1-3.9_
  - [ ]* 7.2 Property test: Context 응답 구조
    - **Property 11: Context Response Structure**
    - **Validates: Requirements 3.7**
  - [ ]* 7.3 Property test: 관계 분류
    - **Property 12: Context Relationship Classification**
    - **Validates: Requirements 3.3**

- [x] 8. Checkpoint - 검색 및 맥락 조회 기능 검증
  - 모든 테스트 통과 확인
  - 검색 및 맥락 조회 동작 확인
  - 질문이 있으면 사용자에게 문의

- [x] 9. 삭제 및 업데이트 기능 완성
  - [x] 9.1 삭제 기능 완성 및 테스트
    - SQLite + 벡터 인덱스 동시 삭제
    - related_memory_ids 참조 정리
    - _Requirements: 4.1-4.5_
  - [ ]* 9.2 Property test: 삭제 완전성
    - **Property 13: Deletion Completeness**
    - **Validates: Requirements 4.2**
  - [x] 9.3 업데이트 기능 완성 및 테스트
    - content 변경 시 재임베딩
    - metadata만 변경 시 임베딩 유지
    - _Requirements: 5.1-5.5_
  - [ ]* 9.4 Property test: 조건부 임베딩 재생성
    - **Property 14: Update Conditional Embedding Regeneration**
    - **Validates: Requirements 5.1, 5.2**

- [x] 10. MCP 서버 구현
  - [x] 10.1 MCP 서버 기본 구조 (src/mcp/server.py)
    - mcp 라이브러리 기반 서버 초기화
    - stdio transport 설정
    - _Requirements: 7.8_
  - [x] 10.2 MCP 도구 등록 (src/mcp/tools.py)
    - mem-mesh.add 도구 스키마 및 핸들러
    - mem-mesh.search 도구 스키마 및 핸들러
    - mem-mesh.context 도구 스키마 및 핸들러
    - mem-mesh.delete 도구 스키마 및 핸들러
    - mem-mesh.update 도구 스키마 및 핸들러
    - _Requirements: 7.1-7.7_
  - [x] 10.3 입력 검증 및 에러 처리
    - 스키마 기반 입력 검증
    - 에러 응답 포맷팅
    - _Requirements: 7.6, 7.7, 9.1_

- [x] 11. Checkpoint - MCP 통합 검증
  - 모든 테스트 통과 확인
  - MCP 도구 호출 테스트
  - 질문이 있으면 사용자에게 문의

- [x] 12. FastAPI 앱 및 진입점 구현
  - [x] 12.1 FastAPI 앱 설정 (src/main.py)
    - 앱 초기화 및 의존성 주입
    - 시작 시 DB 초기화 및 모델 로드
    - _Requirements: 6.9, 6.10, 6.11_
  - [x] 12.2 MCP 서버 진입점 (src/__main__.py)
    - stdio 기반 MCP 서버 실행
    - _Requirements: 7.8_

- [x] 13. 통합 테스트 및 문서화
  - [x] 13.1 E2E 통합 테스트 작성
    - Add → Search 워크플로우
    - Add → Context 워크플로우
    - Add → Update → Search 워크플로우
    - Add → Delete → Search 워크플로우
    - _Requirements: 7.9, 7.10, 7.11_
  - [x] 13.2 README.md 작성
    - 설치 방법
    - 빠른 시작 가이드
    - MCP 설정 예시 (Cursor, Claude Desktop)
    - 환경 변수 설명
  - [x] 13.3 .env.example 작성
    - 모든 설정 옵션 문서화
    - _Requirements: 6.1-6.8_

- [x] 14. Final Checkpoint - 전체 기능 검증
  - 모든 테스트 통과 확인 (커버리지 ≥ 80%)
  - Cursor/Claude Desktop 연동 테스트
  - 질문이 있으면 사용자에게 문의

- [ ] 15. Stats API 구현
  - [ ] 15.1 StatsService 클래스 구현 (src/services/stats.py)
    - get_overall_stats(): 전체 통계 조회
    - get_project_stats(): 프로젝트별 통계
    - get_category_stats(): 카테고리별 통계
    - get_source_stats(): 소스별 통계
    - get_date_range_stats(): 날짜 범위별 통계
    - _Requirements: 10.1-10.10_
  - [ ] 15.2 StatsParams, StatsResponse 스키마 추가 (src/schemas/)
    - StatsParams: project_id, start_date, end_date, group_by 필터
    - StatsResponse: 통계 결과 구조
    - _Requirements: 10.7_
  - [ ] 15.3 FastAPI 엔드포인트 추가 (src/main.py)
    - GET /memories/stats 엔드포인트
    - 쿼리 파라미터 기반 필터링
    - _Requirements: 10.10_
  - [ ] 15.4 MCP 도구 추가 (src/mcp/tools.py)
    - mem-mesh.stats 도구 스키마 및 핸들러
    - _Requirements: 10.10_
  - [ ]* 15.5 Property test: 통계 정확성
    - **Property 18: Statistics Accuracy**
    - **Validates: Requirements 10.1-10.6**
  - [ ]* 15.6 Property test: 필터링 정확성
    - **Property 19: Stats Filtering Accuracy**
    - **Validates: Requirements 10.5, 10.6**
  - [ ]* 15.7 Unit test: 빈 데이터셋 처리
    - 메모리가 없을 때 0 카운트 반환
    - _Requirements: 10.9_

- [ ] 16. Stats API 테스트 및 문서화
  - [ ] 16.1 통합 테스트 추가
    - Add → Stats 워크플로우
    - 다양한 필터 조건 테스트
  - [ ] 16.2 README.md 업데이트
    - /memories/stats 엔드포인트 문서화
    - mem-mesh.stats MCP 도구 설명
  - [ ] 16.3 성능 테스트
    - 100ms 이내 응답 시간 확인
    - _Requirements: 10.8_

- [ ] 17. Final Checkpoint - Stats API 검증
  - 모든 테스트 통과 확인
  - API 응답 시간 검증
  - 질문이 있으면 사용자에게 문의

## Notes

- Tasks marked with `*` are optional property-based tests that can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests use hypothesis library with minimum 100 iterations
- Unit tests complement property tests for edge cases and error conditions
