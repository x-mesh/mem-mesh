# Code Review Report

> **Branch**: `claude/project-differentiation-strategy-6EoKN` vs `main`
> **Date**: 2026-02-26
> **Reviewers**: Sonnet (backend-reviewer, frontend-reviewer)
> **Scope**: 253 files, ~60K lines changed

---

## Critical (7건 — 머지 전 필수 수정)

### C-1. `.env` 파일 커밋 — 관리자 패스워드 노출
- **파일**: `.env:88`
- **내용**: `MEM_MESH_ADMIN_PASSWORD=admin123`이 하드코딩된 채 커밋됨
- **수정**: `.gitignore`에 `.env` 추가, 레포에서 제거, `.env.example`에만 placeholder 유지

### C-2. `/login?error=` XSS
- **파일**: `app/web/oauth/login_routes.py:38-41`
- **내용**: URL 쿼리 파라미터 `error`가 HTML escape 없이 페이지에 직접 삽입
- **수정**: `html.escape(error)` 적용

### C-3. Open Redirect — `next` 파라미터 검증 없음
- **파일**: `app/web/oauth/login_routes.py:56,68,77`, `app/web/oauth/basic_auth.py:304`
- **내용**: `next` 파라미터를 검증 없이 리디렉트에 사용 → 피싱 공격 가능
- **수정**: `next.startswith("/")` 및 `://` 미포함 검증

### C-4. OAuth Authorize에 사용자 인증 없이 auth_code 발급
- **파일**: `app/web/oauth/routes.py:75-116`
- **내용**: 클라이언트 등록만 되면 누구나 authorization code 획득 가능
- **수정**: 세션 확인 → 미인증 시 로그인 리디렉트, 또는 내부 전용 서버 문서화 + 외부 접근 차단

### C-5. SQL Injection 잠재 위험 — DDL에 whitelist 없음
- **파일**: `app/core/database/schema_migrator.py:99,116-120`
- **내용**: `PRAGMA table_info({table})`, `ALTER TABLE {table}` 등에 직접 삽입
- **수정**: `ALLOWED_TABLES = frozenset({...})` 정의 후 whitelist 검증

### C-6. `error.message` → `innerHTML` XSS
- **파일**: `static/js/pages/settings-page.js`
- **내용**: 서버 응답의 error.message가 innerHTML에 비탈출 삽입
- **수정**: `escapeHtml(error.message)` 또는 `textContent` 사용

### C-7. docker-compose 프로덕션에 소스 코드 마운트
- **파일**: `docker/docker-compose.yml:15-17`
- **내용**: 기본 compose 파일에 호스트 소스 마운트 → 프로덕션 혼용 시 파일시스템 노출
- **수정**: `docker-compose.override.yml`로 분리

---

## Warning (10건 — 수정 권장)

### W-1. Refresh Token 평문 DB 저장
- **파일**: `app/core/auth/models.py:165`, `app/core/auth/service.py:851`
- **수정**: `refresh_token_hash`로 해시 저장

### W-2. 클라이언트 시크릿 해싱에 Salt 없음
- **파일**: `app/core/auth/utils.py:48-56`
- **수정**: `hashlib.pbkdf2_hmac` 또는 `bcrypt` 사용

### W-3. Session Cookie에 `secure=True` 없음
- **파일**: `app/web/oauth/login_routes.py:70-76`
- **수정**: 프로덕션에서 `secure=True` 추가

### W-4. `batch_operations` add — 첫 항목 메타데이터만 적용
- **파일**: `app/mcp_common/batch_tools.py:258-265`
- **수정**: 각 operation의 `project_id`/`category`를 개별 적용

### W-5. `INSERT OR REPLACE` 프로젝트 규칙 위반
- **파일**: `app/core/database/schema_migrator.py:109-111`
- **수정**: DELETE + INSERT 패턴으로 교체

### W-6. 타입 힌트 오류 `str = None`
- **파일**: `app/core/auth/service.py:48`
- **수정**: `Optional[str] = None`

### W-7. Chart modal `innerHTML` chain XSS
- **파일**: `static/js/components/chroma-charts.js`
- **수정**: `cloneNode(true)`로 DOM 노드 복제 삽입

### W-8. `torch` 버전 미고정
- **파일**: `requirements.txt:46`
- **수정**: `torch>=2.0.0,<3.0.0` 명시

### W-9. 통합 테스트 삭제 후 미대체
- **파일**: `tests/test_integration.py` (삭제됨)
- **수정**: 대체 통합 테스트 모듈 작성

### W-10. docker-compose `version: '3.8'` deprecated
- **파일**: `docker/docker-compose.yml:1`
- **수정**: `version` 키 제거

---

## 긍정적 변경사항

- MCPDispatcher 도입으로 355줄 중복 제거
- Database 모듈 분리 (connection/initializer/migrator)
- UnifiedSearchService + RRF 하이브리드 검색
- Docker non-root 사용자 적용
- `escapeHtml()` XSS 방지 패턴 적용 (alert-panel)
- CI 강화 (ruff, pytest --cov, isort)
- Makefile 자동 문서화
- E5 모델 prefix 지원 (query/passage)
- OAuth 2.1 + PKCE 구현
- 에러 코드 중앙화 (`app/core/errors.py`)
- SchemaMigrator 자동 마이그레이션
