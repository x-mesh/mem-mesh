# Code Review Fix Plan

> 2026-02-26 코드 리뷰 결과 기반 수정 계획
> 참조: [docs/CODE_REVIEW_2026-02-26.md](./CODE_REVIEW_2026-02-26.md)

---

## Phase 1: Critical 보안 수정 (즉시)

### Task 1.1 — `.env` 제거 및 `.gitignore` 업데이트
- [ ] `.gitignore`에 `.env` 추가
- [ ] `git rm --cached .env`로 추적 제거
- [ ] `.env.example` placeholder 확인
- **파일**: `.env`, `.gitignore`, `.env.example`

### Task 1.2 — XSS 수정 (login error + settings-page)
- [ ] `app/web/oauth/login_routes.py:38-41` — `html.escape(error)` 적용
- [ ] `static/js/pages/settings-page.js` — `escapeHtml()` 또는 `textContent` 사용
- **파일**: `app/web/oauth/login_routes.py`, `static/js/pages/settings-page.js`

### Task 1.3 — Open Redirect 방지
- [ ] `next` 파라미터에 `startswith("/")` 및 `://` 미포함 검증 추가
- [ ] 검증 실패 시 기본 경로(`/`)로 리디렉트
- **파일**: `app/web/oauth/login_routes.py`, `app/web/oauth/basic_auth.py`

### Task 1.4 — OAuth Authorize 인증 강화
- [ ] authorize 엔드포인트에 세션 확인 로직 추가
- [ ] 미인증 시 `/login?next=` 리디렉트
- [ ] 또는 내부 전용 서버 문서화 + 네트워크 레벨 접근 제한 명시
- **파일**: `app/web/oauth/routes.py`

### Task 1.5 — SQL Injection 방지 (DDL whitelist)
- [ ] `ALLOWED_TABLES` frozenset 정의
- [ ] `schema_migrator.py`에서 table/column 이름 whitelist 검증
- **파일**: `app/core/database/schema_migrator.py`

### Task 1.6 — docker-compose 분리
- [ ] `docker-compose.yml`에서 소스 마운트 제거
- [ ] `docker-compose.override.yml`로 개발용 마운트 분리
- **파일**: `docker/docker-compose.yml`, `docker/docker-compose.override.yml`

---

## Phase 2: Warning 보안 강화

### Task 2.1 — Auth 보안 강화
- [ ] Refresh token 해시 저장 (`refresh_token_hash`)
- [ ] `hash_secret()` — `hashlib.pbkdf2_hmac` 또는 `bcrypt`로 교체
- [ ] Session cookie에 프로덕션 `secure=True` 추가
- [ ] `OAuthError.__init__` 타입 힌트 수정 (`Optional[str]`)
- **파일**: `app/core/auth/models.py`, `app/core/auth/utils.py`, `app/core/auth/service.py`, `app/web/oauth/login_routes.py`

### Task 2.2 — 프론트엔드 XSS 추가 수정
- [ ] `chroma-charts.js` — `cloneNode(true)` 방식으로 변경
- **파일**: `static/js/components/chroma-charts.js`

---

## Phase 3: 버그 및 규칙 준수

### Task 3.1 — `batch_operations` add 메타데이터 버그 수정
- [ ] 각 operation의 `project_id`/`category`/`tags`를 개별 적용하도록 수정
- **파일**: `app/mcp_common/batch_tools.py`

### Task 3.2 — `INSERT OR REPLACE` → DELETE + INSERT
- [ ] `schema_migrator.py`에서 INSERT OR REPLACE 패턴 교체
- **파일**: `app/core/database/schema_migrator.py`

---

## Phase 4: 설정 및 인프라

### Task 4.1 — 의존성 정리
- [ ] `torch` 버전 pinning (`>=2.0.0,<3.0.0`)
- [ ] `docker-compose.yml`에서 `version` 키 제거
- **파일**: `requirements.txt`, `docker/docker-compose.yml`

### Task 4.2 — 통합 테스트 복구
- [ ] 삭제된 `test_integration.py` 대체 테스트 작성
- [ ] E2E 워크플로우 (add→search→context→update→delete) 커버
- **파일**: `tests/test_integration_v2.py` (신규)

---

## 진행 순서

```
Phase 1 (Critical) → Phase 2 (Auth 보안) → Phase 3 (버그) → Phase 4 (인프라/테스트)
```

Phase 1 완료 후 머지 가능. Phase 2~4는 후속 PR로 분리 가능.
