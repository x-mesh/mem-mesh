# Implementation Plan: Work Tracking System

## Overview

Work Tracking System 구현을 위한 단계별 작업 목록입니다. 기존 mem-mesh 코드베이스에 projects, sessions, pins 테이블과 관련 서비스를 추가합니다.

## Tasks

- [x] 1. 데이터베이스 스키마 확장
  - [x] 1.1 projects, sessions, pins 테이블 생성
    - `app/core/database/base.py`에 테이블 생성 SQL 추가
    - 인덱스 생성 포함
    - _Requirements: 1.1, 1.2, 2.2, 3.2, 8.1_

  - [x] 1.2 사용자 식별 유틸리티 구현
    - `app/core/utils/user.py` 생성
    - `whoami` 또는 `USER` 환경변수로 사용자명 자동 감지
    - 기본값 "default" 반환
    - _Requirements: 8.2, 8.3, 8.5_

- [x] 2. Pydantic 스키마 정의
  - [x] 2.1 Pin 관련 스키마 생성
    - `app/core/schemas/pins.py` 생성
    - PinCreate, PinUpdate, PinResponse 정의
    - _Requirements: 3.2_

  - [x] 2.2 Session 관련 스키마 생성
    - `app/core/schemas/sessions.py` 생성
    - SessionCreate, SessionContext, SessionResponse 정의
    - _Requirements: 2.2_

  - [x] 2.3 Project 관련 스키마 생성
    - `app/core/schemas/projects.py` 생성
    - ProjectCreate, ProjectUpdate, ProjectWithStats 정의
    - _Requirements: 1.2_

- [x] 3. 서비스 레이어 구현
  - [x] 3.1 ProjectService 구현
    - `app/core/services/project.py` 생성
    - get_or_create_project, update_project, list_projects_with_stats
    - _Requirements: 1.1, 1.3, 1.4_

  - [x] 3.2 Property test: Auto-creation Chain
    - **Property 1: Auto-creation Chain**
    - 랜덤 project_id로 project 생성 시 자동 생성 검증
    - **Validates: Requirements 1.1**

  - [x] 3.3 SessionService 구현
    - `app/core/services/session.py` 생성
    - get_or_create_active_session, resume_last_session, end_session
    - pause_inactive_sessions (4시간 비활동 시)
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6_

  - [x] 3.4 Property test: Session Reuse
    - **Property 2: Session Reuse**
    - 같은 프로젝트에 여러 pin 생성 시 동일 세션 할당 검증
    - **Validates: Requirements 2.1, 3.1**

  - [x] 3.5 PinService 구현
    - `app/core/services/pin.py` 생성
    - create_pin, complete_pin, promote_to_memory, get_pins_by_session, delete_pin
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.4, 4.5_

  - [x] 3.6 Property test: Pin Completion Timestamps
    - **Property 3: Pin Completion Timestamps**
    - 완료된 pin의 completed_at과 lead_time 계산 검증
    - **Validates: Requirements 3.5, 3.6**

  - [x] 3.7 Property test: Status Transitions
    - **Property 4: Status Transitions**
    - 유효한 상태 전이만 허용되는지 검증
    - **Validates: Requirements 3.4**

  - [x] 3.8 Property test: Pin Promotion Round-trip
    - **Property 5: Pin Promotion Round-trip**
    - 승격된 pin과 Memory의 content, tags 일치 검증
    - **Validates: Requirements 4.2**

- [x] 4. Checkpoint - 서비스 레이어 검증
  - 모든 서비스 테스트 통과 확인
  - 질문 있으면 사용자에게 문의

- [x] 5. MCP Tools 구현
  - [x] 5.1 pin_add 도구 구현
    - `app/mcp_common/tools.py`에 추가
    - 세션 자동 관리 포함
    - _Requirements: 7.1, 7.6_

  - [x] 5.2 pin_complete 도구 구현
    - importance >= 4일 때 승격 제안 포함
    - _Requirements: 7.2, 4.1_

  - [x] 5.3 pin_promote 도구 구현
    - Memory로 승격 및 embedding 생성
    - _Requirements: 7.3_

  - [x] 5.4 session_resume 도구 구현
    - expand, limit 파라미터 지원
    - 토큰 효율적 컨텍스트 로드
    - _Requirements: 7.4, 5.1, 5.2, 5.3, 5.4_

  - [x] 5.5 Property test: Context Load Efficiency
    - **Property 6: Context Load Efficiency**
    - expand=False 시 요약만 반환, importance 정렬, limit 적용 검증
    - **Validates: Requirements 5.1, 5.3, 5.4**

  - [x] 5.6 session_end 도구 구현
    - 세션 종료 및 요약 생성
    - _Requirements: 7.5_

  - [x] 5.7 Property test: User Filtering
    - **Property 8: User Filtering**
    - user_id 필터링 및 기본값 "default" 검증
    - **Validates: Requirements 8.2, 8.4**

- [x] 6. Checkpoint - MCP Tools 검증
  - 모든 MCP tool 테스트 통과 확인
  - 질문 있으면 사용자에게 문의

- [x] 7. 통계 서비스 확장
  - [x] 7.1 StatsService에 Lead Time 통계 추가
    - average_lead_time 계산 로직 추가
    - 일별/주별 pin 완료 수 집계
    - 상태별 pin 수 집계
    - _Requirements: 6.1, 6.2, 6.4_

  - [x] 7.2 Property test: Lead Time Statistics
    - **Property 7: Lead Time Statistics**
    - 평균 lead_time 계산 정확성 검증
    - **Validates: Requirements 6.1**

- [x] 8. REST API 엔드포인트 추가
  - [x] 8.1 Pin 관련 API 추가
    - `app/web/dashboard/routes.py`에 추가
    - POST /api/work/pins, PUT /api/work/pins/{id}/complete, POST /api/work/pins/{id}/promote
    - GET /api/work/pins?session_id=&project_id=
    - _Requirements: 3.1, 3.4, 4.2_

  - [x] 8.2 Session 관련 API 추가
    - `app/web/dashboard/routes.py`에 추가
    - GET /api/work/sessions/resume/{project_id}, POST /api/work/sessions/{id}/end
    - _Requirements: 2.4, 2.5_

  - [x] 8.3 Project 관련 API 확장
    - GET /api/work/projects, GET /api/work/projects/{id}/stats
    - _Requirements: 1.4, 6.1_

- [x] 9. Dashboard 통계 연동
  - [x] 9.1 Dashboard에 Avg Lead Time 표시
    - `static/js/pages/dashboard.js` 수정
    - 실제 pin 데이터 기반 lead_time 표시
    - _Requirements: 6.3_

- [x] 10. Final Checkpoint
  - 모든 테스트 통과 확인
  - REST API 엔드포인트 추가 완료
  - Dashboard 통계 연동 완료

## Notes

- All property-based tests are required
- 기존 memories 테이블은 변경하지 않음 (공존)
- 마이그레이션 없음 - 새 데이터만 적용
- Python 3.9+, Hypothesis 라이브러리 사용
