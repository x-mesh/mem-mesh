# 구현 계획: context-token-optimization

## 개요

이 구현 계획은 mem-mesh 시스템의 토큰 최적화 기능을 단계적으로 구현합니다. 기존 Pin/Session 시스템을 확장하고, 새로운 토큰 추적 및 최적화 레이어를 추가하여 AI 도구 사용 시 토큰 사용량을 최대 95%까지 절감합니다.

## 작업 목록

- [x] 1. 데이터베이스 스키마 확장 및 마이그레이션
  - 기존 pins, sessions 테이블에 토큰 추적 컬럼 추가
  - session_stats, token_usage 신규 테이블 생성
  - 필요한 인덱스 생성
  - 마이그레이션 스크립트 작성 및 테스트
  - _Requirements: 10.1, 10.2, 10.3_

- [ ]* 1.1 데이터베이스 스키마 테스트 작성
  - 테이블 생성 확인 테스트
  - 인덱스 존재 확인 테스트
  - WAL 모드 활성화 확인 테스트
  - _Requirements: 10.1, 10.2, 10.3_

- [ ] 2. TokenTracker 서비스 구현
  - [x] 2.1 TokenEstimator 클래스 구현
    - 텍스트 토큰 수 추정 로직 (tiktoken 라이브러리 사용)
    - 다양한 모델 지원 (gpt-3.5-turbo, gpt-4 등)
    - _Requirements: 7.1, 7.2_
  
  - [x] 2.2 TokenTracker 클래스 구현
    - estimate_tokens() 메서드
    - record_session_tokens() 메서드
    - calculate_savings() 메서드
    - check_threshold() 메서드
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  
  - [ ]* 2.3 TokenTracker 속성 테스트 작성
    - **Property 19: 세션 토큰 추적**
    - **Validates: Requirements 7.1, 7.2**
  
  - [ ]* 2.4 TokenTracker 속성 테스트 작성
    - **Property 20: 세션 종료 시 토큰 절감률 계산**
    - **Validates: Requirements 7.3**
  
  - [ ]* 2.5 TokenTracker 속성 테스트 작성
    - **Property 21: 지연 로딩 시 미로드 토큰 추적**
    - **Validates: Requirements 7.4**
  
  - [ ]* 2.6 TokenTracker 속성 테스트 작성
    - **Property 22: 토큰 임계값 초과 시 경고**
    - **Validates: Requirements 7.5**

- [ ] 3. ImportanceAnalyzer 서비스 구현
  - [x] 3.1 ImportanceAnalyzer 클래스 구현
    - 키워드 기반 중요도 분석 로직
    - 한국어/영어 키워드 사전 로드
    - analyze() 메서드 구현
    - _Requirements: 2.2_
  
  - [ ]* 3.2 ImportanceAnalyzer 속성 테스트 작성
    - **Property 5: 핀 생성 시 자동 중요도 추정**
    - **Validates: Requirements 2.2**
  
  - [ ]* 3.3 ImportanceAnalyzer 단위 테스트 작성
    - 다양한 키워드 조합 테스트
    - 엣지 케이스 (빈 문자열, 특수문자 등)
    - _Requirements: 2.2_

- [ ] 4. ContextOptimizer 서비스 구현
  - [x] 4.1 ContextOptimizer 클래스 구현
    - adjust_for_intent() 메서드
    - load_context_for_search() 메서드
    - 의도별 파라미터 조정 로직
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  
  - [ ]* 4.2 ContextOptimizer 속성 테스트 작성
    - **Property 16: 의도 기반 맥락 조정**
    - **Validates: Requirements 6.1, 6.2, 6.3**
  
  - [ ]* 4.3 ContextOptimizer 속성 테스트 작성
    - **Property 17: 의도 불명확 시 기본 모드 사용**
    - **Validates: Requirements 6.4**
  
  - [ ]* 4.4 ContextOptimizer 속성 테스트 작성
    - **Property 18: 맥락 조정 시 토큰 수 반환**
    - **Validates: Requirements 6.5**

- [x] 5. Checkpoint - 핵심 서비스 검증
  - 모든 신규 서비스 테스트 통과 확인
  - 사용자에게 질문이 있으면 확인

- [ ] 6. PinService 확장
  - [x] 6.1 필터링 메서드 추가
    - get_pins_filtered() 메서드 구현
    - importance, status, tags 필터 지원
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  
  - [x] 6.2 통계 메서드 추가
    - get_pin_statistics() 메서드 구현
    - 중요도별 분포, 상태별 분포 계산
    - _Requirements: 9.4_
  
  - [x] 6.3 승격 로직 개선
    - 중복 승격 방지 로직 추가
    - promoted_to_memory_id 컬럼 활용
    - _Requirements: 4.5_
  
  - [ ]* 6.4 PinService 속성 테스트 작성 (기본 불변성)
    - **Property 4: 핀 생성 시 기본 불변성**
    - **Validates: Requirements 2.1, 2.4, 2.5**
  
  - [ ]* 6.5 PinService 속성 테스트 작성 (importance 검증)
    - **Property 6: 핀 생성 시 importance 범위 검증**
    - **Validates: Requirements 2.3**
  
  - [ ]* 6.6 PinService 속성 테스트 작성 (완료 처리)
    - **Property 7: 핀 완료 시 상태 변경 및 시각 기록**
    - **Validates: Requirements 3.1**
  
  - [ ]* 6.7 PinService 속성 테스트 작성 (승격 제안)
    - **Property 8: 핀 완료 시 중요도 기반 승격 제안**
    - **Validates: Requirements 3.2, 3.3**
  
  - [ ]* 6.8 PinService 속성 테스트 작성 (lead_time)
    - **Property 9: 핀 완료 시 lead_time 자동 계산**
    - **Validates: Requirements 3.5**
  
  - [ ]* 6.9 PinService 속성 테스트 작성 (승격)
    - **Property 10: 핀 승격 시 메모리 생성 및 ID 반환**
    - **Validates: Requirements 4.1**
  
  - [ ]* 6.10 PinService 속성 테스트 작성 (메타데이터 보존)
    - **Property 11: 핀 승격 시 메타데이터 보존**
    - **Validates: Requirements 4.2, 4.3, 4.4**
  
  - [ ]* 6.11 PinService 속성 테스트 작성 (중복 방지)
    - **Property 12: 핀 중복 승격 방지**
    - **Validates: Requirements 4.5**
  
  - [ ]* 6.12 PinService 속성 테스트 작성 (필터링)
    - **Property 23: 핀 필터링 기능**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
  
  - [ ]* 6.13 PinService 속성 테스트 작성 (정렬)
    - **Property 24: 핀 검색 결과 정렬**
    - **Validates: Requirements 8.5**

- [ ] 7. SessionService 확장
  - [x] 7.1 토큰 추적 통합
    - resume_with_token_tracking() 메서드 구현
    - TokenTracker 서비스 통합
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 7.1, 7.2_
  
  - [x] 7.2 자동 승격 기능 추가
    - end_with_auto_promotion() 메서드 구현
    - importance >= 4인 완료된 핀 자동 승격
    - _Requirements: 5.4_
  
  - [x] 7.3 세션 통계 메서드 추가
    - get_session_statistics() 메서드 구현
    - 프로젝트별, 기간별 통계 지원
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  
  - [ ]* 7.4 SessionService 속성 테스트 작성 (expand 파라미터)
    - **Property 1: 세션 재개 시 expand 파라미터에 따른 맥락 로딩**
    - **Validates: Requirements 1.1, 1.2**
  
  - [ ]* 7.5 SessionService 속성 테스트 작성 (limit)
    - **Property 2: 세션 재개 시 limit 파라미터 준수**
    - **Validates: Requirements 1.3**
  
  - [ ]* 7.6 SessionService 속성 테스트 작성 (필수 필드)
    - **Property 3: 세션 재개 시 필수 필드 포함**
    - **Validates: Requirements 1.5**
  
  - [ ]* 7.7 SessionService 속성 테스트 작성 (요약 생성)
    - **Property 13: 세션 종료 시 요약 생성**
    - **Validates: Requirements 5.1, 5.2, 5.3**
  
  - [ ]* 7.8 SessionService 속성 테스트 작성 (자동 승격)
    - **Property 14: 세션 종료 시 자동 승격 제안**
    - **Validates: Requirements 5.4**
  
  - [ ]* 7.9 SessionService 속성 테스트 작성 (통계)
    - **Property 15: 세션 종료 시 통계 반환**
    - **Validates: Requirements 5.5**
  
  - [ ]* 7.10 SessionService 속성 테스트 작성 (세션 통계)
    - **Property 25: 세션 통계 완전성**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

- [ ] 8. UnifiedSearchService 통합
  - [x] 8.1 맥락 최적화 메서드 추가
    - search_with_context_optimization() 메서드 구현
    - ContextOptimizer 통합
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  
  - [ ]* 8.2 통합 테스트 작성
    - 검색 + 맥락 최적화 통합 시나리오
    - 다양한 의도별 테스트
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [~] 9. Checkpoint - 서비스 통합 검증
  - 모든 확장된 서비스 테스트 통과 확인
  - 통합 시나리오 테스트 실행
  - 사용자에게 질문이 있으면 확인

- [ ] 10. MCP Tool 핸들러 업데이트
  - [x] 10.1 session_resume 도구 업데이트
    - 토큰 추적 정보 포함
    - expand, limit 파라미터 지원 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.5_
  
  - [x] 10.2 pin_add 도구 업데이트
    - ImportanceAnalyzer 통합
    - 자동 중요도 추정 지원
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  
  - [~] 10.3 pin_complete 도구 업데이트
    - 승격 제안 로직 통합
    - lead_time 계산 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.5_
  
  - [~] 10.4 pin_promote 도구 업데이트
    - 중복 승격 방지 로직 확인
    - 메타데이터 보존 확인
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  
  - [~] 10.5 session_end 도구 업데이트
    - 자동 승격 기능 통합
    - 토큰 절감 통계 포함
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [~] 11. Pydantic 스키마 추가
  - app/core/schemas/optimization.py 파일 생성
  - TokenInfo, SessionStatistics, PinStatistics, OptimizedSessionContext 스키마 정의
  - 기존 스키마와의 호환성 확인
  - _Requirements: 전체_

- [ ] 12. 데이터베이스 정리 기능 구현
  - [~] 12.1 오래된 핀 정리 로직
    - 30일 이상 경과한 미승격 핀 식별
    - 정리 실행 메서드 구현
    - _Requirements: 10.4, 10.5_
  
  - [ ]* 12.2 정리 기능 속성 테스트 작성
    - **Property 26: 오래된 핀 자동 정리**
    - **Validates: Requirements 10.4, 10.5**
  
  - [~] 12.3 정리 스케줄러 구현
    - 주기적 정리 작업 스케줄링
    - 설정 가능한 정리 주기
    - _Requirements: 10.4, 10.5_

- [x] 13. 에러 처리 및 로깅 개선
  - 새로운 에러 클래스 정의 (TokenLimitExceededError, InvalidImportanceError 등)
  - 구조화된 로깅 추가 (토큰 사용량, 절감률 등)
  - 에러 응답 형식 표준화
  - _Requirements: 전체_

- [~] 14. Checkpoint - 전체 기능 검증
  - 모든 테스트 통과 확인 (단위 + 속성 + 통합)
  - 코드 커버리지 85% 이상 확인
  - 사용자에게 질문이 있으면 확인

- [ ] 15. 통합 테스트 및 시나리오 테스트
  - [~] 15.1 전체 워크플로우 통합 테스트
    - 세션 시작 → 핀 추가 → 검색 → 완료 → 종료 전체 흐름
    - 토큰 추적 및 절감률 검증
    - _Requirements: 전체_
  
  - [ ]* 15.2 성능 테스트
    - 1000개 핀 세션에서 1초 이내 응답 확인
    - 토큰 추정 성능 측정
    - _Requirements: 10.3_
  
  - [ ]* 15.3 동시성 테스트
    - 여러 세션 동시 처리
    - WAL 모드 동시성 확인
    - _Requirements: 10.3_

- [~] 16. 문서화
  - API 문서 업데이트 (새로운 파라미터 및 응답 형식)
  - 사용 예제 작성 (토큰 최적화 워크플로우)
  - 설정 가이드 작성 (임계값, 정리 주기 등)
  - _Requirements: 전체_

- [x] 17. 최종 검증 및 배포 준비
  - 모든 테스트 최종 실행
  - 마이그레이션 스크립트 검증
  - 롤백 계획 수립
  - 배포 체크리스트 작성

## 참고사항

- `*` 표시된 작업은 선택적(optional)이며, 빠른 MVP를 위해 건너뛸 수 있습니다
- 각 작업은 이전 작업에 의존하므로 순서대로 진행해야 합니다
- Checkpoint 작업에서는 반드시 사용자 확인을 받아야 합니다
- 모든 속성 테스트는 hypothesis 라이브러리를 사용하며 최소 100회 반복합니다
- 테스트 태그 형식: `Feature: context-token-optimization, Property {번호}: {제목}`
