# Implementation Plan: MCP Direct SQLite & Architecture Refactoring

## Overview

이 구현 계획은 mem-mesh 시스템의 아키텍처를 개선하여 MCP 서버가 직접 SQLite에 접근할 수 있도록 하고, FastMCP 라이브러리를 사용한 새로운 MCP 구현을 제공하며, Docker 및 Makefile을 통한 배포 자동화를 구현합니다.

## Tasks

- [x] 1. 프로젝트 구조 설정 및 의존성 추가
  - [x] 1.1 app/ 디렉토리 구조 생성
    - `app/__init__.py`, `app/core/__init__.py`, `app/mcp/__init__.py`, `app/dashboard/__init__.py` 생성
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [x] 1.2 pyproject.toml에 FastMCP 및 httpx 의존성 추가
    - fastmcp, httpx 패키지 추가
    - 새로운 진입점 스크립트 정의
    - _Requirements: 8.1_

- [x] 2. Core 모듈 구현 (app/core/)
  - [x] 2.1 설정 모듈 구현 (app/core/config.py)
    - storage_mode, api_base_url, busy_timeout 설정 추가
    - 환경변수 및 .env 파일 지원
    - _Requirements: 1.1, 1.4, 1.5, 7.1, 7.2, 7.3, 7.4, 7.5_
  - [ ]* 2.2 설정 속성 테스트 작성
    - **Property 1: Settings Configuration Round-Trip**
    - **Property 2: Invalid Storage Mode Rejection**
    - **Validates: Requirements 1.1, 1.5, 7.1-7.4**
  - [x] 2.3 데이터베이스 모듈 복사 및 WAL 설정 강화 (app/core/database/)
    - 기존 src/database/ 코드를 app/core/database/로 복사
    - busy_timeout 설정 추가
    - _Requirements: 4.1, 4.4_
  - [x] 2.4 임베딩 서비스 복사 (app/core/embeddings/)
    - 기존 src/embeddings/ 코드를 app/core/embeddings/로 복사
    - _Requirements: 8.7_
  - [x] 2.5 비즈니스 서비스 복사 (app/core/services/)
    - 기존 src/services/ 코드를 app/core/services/로 복사
    - _Requirements: 8.7_
  - [x] 2.6 스키마 복사 (app/core/schemas/)
    - 기존 src/schemas/ 코드를 app/core/schemas/로 복사
    - _Requirements: 8.7_

- [x] 3. Storage Abstraction Layer 구현
  - [x] 3.1 StorageBackend 추상 인터페이스 구현 (app/core/storage/base.py)
    - 6개 메서드 정의 (add, search, context, update, delete, stats)
    - _Requirements: 2.1-2.6, 3.1_
  - [x] 3.2 DirectStorageBackend 구현 (app/core/storage/direct.py)
    - SQLite 직접 접근 구현
    - 기존 서비스 레이어 활용
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - [ ]* 3.3 Direct 모드 속성 테스트 작성
    - **Property 3: Direct Mode Tool Operations**
    - **Validates: Requirements 2.1-2.6**
  - [x] 3.4 APIStorageBackend 구현 (app/core/storage/api.py)
    - httpx를 사용한 HTTP 클라이언트 구현
    - 재시도 로직 구현
    - _Requirements: 3.1, 3.2, 3.3_
  - [ ]* 3.5 API 모드 에러 처리 속성 테스트 작성
    - **Property 4: API Mode Error Handling**
    - **Validates: Requirements 3.2**

- [x] 4. Checkpoint - Core 모듈 테스트
  - 모든 테스트가 통과하는지 확인
  - 문제가 있으면 사용자에게 질문

- [x] 5. FastMCP 서버 구현 (app/mcp/)
  - [x] 5.1 FastMCP 서버 기본 구조 구현 (app/mcp/server.py)
    - FastMCP 인스턴스 생성
    - storage 초기화 함수 구현
    - _Requirements: 8.1, 8.4_
  - [x] 5.2 MCP 도구 구현 - add, search (app/mcp/server.py)
    - @mcp.tool() 데코레이터 사용
    - StorageBackend 호출
    - _Requirements: 8.2, 8.6_
  - [x] 5.3 MCP 도구 구현 - context, update, delete, stats (app/mcp/server.py)
    - 나머지 4개 도구 구현
    - _Requirements: 8.2, 8.6_
  - [x] 5.4 MCP 진입점 구현 (app/mcp/__main__.py)
    - python -m app.mcp 실행 가능하도록
    - _Requirements: 8.5, 9.5_
  - [ ]* 5.5 FastMCP 서버 단위 테스트 작성
    - 6개 도구 등록 확인
    - 도구 호출 테스트
    - _Requirements: 8.2_

- [x] 6. FastAPI Dashboard 구현 (app/dashboard/)
  - [x] 6.1 FastAPI 앱 구현 (app/dashboard/main.py)
    - 기존 src/main.py 코드를 app/dashboard/main.py로 이동
    - import 경로 수정
    - _Requirements: 9.3_
  - [x] 6.2 Dashboard 진입점 구현 (app/dashboard/__main__.py)
    - python -m app.dashboard 실행 가능하도록
    - _Requirements: 9.6_
  - [ ]* 6.3 Dashboard 단위 테스트 작성
    - API 엔드포인트 테스트
    - _Requirements: 9.6_

- [x] 7. Checkpoint - MCP 및 Dashboard 테스트
  - 모든 테스트가 통과하는지 확인
  - python -m app.mcp 및 python -m app.dashboard 실행 확인
  - 문제가 있으면 사용자에게 질문

- [x] 8. 동시성 테스트 구현
  - [x]* 8.1 동시 접근 안정성 속성 테스트 작성
    - **Property 5: Concurrent Database Access Stability**
    - **Validates: Requirements 4.2, 4.3**
  - [x] 8.2 스토리지 백엔드 일관성 속성 테스트 작성
    - **Property 6: Storage Backend Interface Consistency**
    - **Validates: Requirements 2.1-2.6, 3.1**

- [ ] 9. Docker 설정 구현
  - [ ] 9.1 Dockerfile.mcp 작성 (docker/Dockerfile.mcp)
    - MCP 서버용 Docker 이미지
    - _Requirements: 5.2_
  - [ ] 9.2 Dockerfile.dashboard 작성 (docker/Dockerfile.dashboard)
    - FastAPI 대시보드용 Docker 이미지
    - _Requirements: 5.1_
  - [ ] 9.3 docker-compose.yml 작성 (docker/docker-compose.yml)
    - 볼륨 공유 설정
    - 환경변수 설정
    - _Requirements: 5.3, 5.4, 5.5_

- [ ] 10. Makefile 작성
  - [ ] 10.1 Makefile 생성
    - install, run-api, run-mcp, test, docker-build, docker-up, clean 명령
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

- [ ] 11. 문서 및 설정 파일 업데이트
  - [ ] 11.1 .env.example 업데이트
    - 새로운 환경변수 추가
    - _Requirements: 7.4_
  - [ ] 11.2 pyproject.toml 진입점 업데이트
    - mem-mesh-mcp, mem-mesh-dashboard 스크립트 추가
    - _Requirements: 8.5, 9.5, 9.6_

- [ ] 12. Final Checkpoint - 전체 통합 테스트
  - 모든 테스트가 통과하는지 확인
  - Docker 빌드 및 실행 확인
  - Makefile 명령어 동작 확인
  - 문제가 있으면 사용자에게 질문

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 기존 `src/` 디렉토리는 하위 호환성을 위해 유지됩니다
- 각 태스크는 특정 요구사항을 참조하여 추적 가능합니다
- Checkpoint에서 테스트 실패 시 진행을 멈추고 사용자에게 확인합니다
- Property 테스트는 Hypothesis 라이브러리를 사용하여 최소 100회 반복 실행합니다
