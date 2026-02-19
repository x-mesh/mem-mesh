# mem-mesh Docker 배포 가이드

mem-mesh를 Docker를 사용하여 배포하는 방법을 설명합니다.

## 빠른 시작

### 1. Dashboard 실행 (권장)

```bash
# Docker Compose로 대시보드 시작
make docker-up

# 또는 직접 실행
docker compose -f docker/docker-compose.yml up -d dashboard
```

대시보드 접속: http://localhost:8000

### 2. MCP 서버 실행 (선택적)

```bash
# MCP 서버 포함하여 모든 서비스 시작
make docker-up-all

# 또는 직접 실행
docker compose -f docker/docker-compose.yml --profile mcp up -d
```

## 사용 가능한 이미지

### 1. Dashboard (mem-mesh-dashboard)

FastAPI 웹 대시보드 + REST API + MCP SSE 엔드포인트

**포트:**
- 8000: Web Dashboard + REST API
- 8001: MCP SSE endpoint

**환경변수:**
- `DATABASE_PATH`: SQLite 데이터베이스 경로 (기본값: `/app/data/memories.db`)
- `STORAGE_MODE`: 스토리지 모드 (기본값: `direct`)
- `HOST`: 서버 호스트 (기본값: `0.0.0.0`)
- `PORT`: 서버 포트 (기본값: `8000`)
- `LOG_LEVEL`: 로그 레벨 (기본값: `info`)
- `EMBEDDING_MODEL`: 임베딩 모델 (기본값: `sentence-transformers/all-MiniLM-L6-v2`)
- `EMBEDDING_DEVICE`: 임베딩 디바이스 (기본값: `cpu`)
- `BUSY_TIMEOUT`: SQLite busy timeout (기본값: `30000`)

### 2. MCP Server (mem-mesh-mcp)

MCP stdio 서버 (CLI 사용)

**환경변수:**
- `DATABASE_PATH`: SQLite 데이터베이스 경로
- `STORAGE_MODE`: 스토리지 모드 (기본값: `direct`)
- `MCP_LOG_FORMAT`: MCP 로그 형식 (기본값: `text`)
- `EMBEDDING_MODEL`: 임베딩 모델
- `EMBEDDING_DEVICE`: 임베딩 디바이스
- `BUSY_TIMEOUT`: SQLite busy timeout

## Makefile 명령어

### 개발

```bash
make install          # 의존성 설치
make install-dev      # 개발 의존성 포함 설치
make test             # 테스트 실행
make test-cov         # 커버리지 포함 테스트
make run-api          # 개발 서버 실행 (hot-reload)
make run-mcp          # MCP stdio 서버 실행
```

### Docker

```bash
make docker-build           # 모든 이미지 빌드
make docker-build-dashboard # Dashboard 이미지만 빌드
make docker-build-mcp       # MCP 서버 이미지만 빌드

make docker-up              # Dashboard 시작
make docker-up-all          # 모든 서비스 시작 (MCP 포함)
make docker-down            # 서비스 중지
make docker-restart         # 서비스 재시작
make docker-clean           # 컨테이너 및 볼륨 삭제

make docker-logs            # 모든 로그 보기
make docker-logs-dashboard  # Dashboard 로그만 보기
make docker-logs-mcp        # MCP 서버 로그만 보기
```

### 유틸리티

```bash
make format           # 코드 포맷팅 (Black)
make lint             # 코드 린팅 (Ruff)
make lint-fix         # 린팅 및 자동 수정
make clean            # 생성된 파일 정리

make migrate          # 데이터베이스 마이그레이션
make migrate-check    # 마이그레이션 확인 (dry-run)

make db-backup        # 데이터베이스 백업
make db-restore       # 최신 백업에서 복원

make health-check     # 서비스 헬스 체크
```

### 빠른 시작

```bash
make dev              # 개발 환경 시작 (install-dev + run-api)
make prod             # 프로덕션 환경 시작 (docker-build + docker-up)
make stop             # 모든 서비스 중지
```

## 볼륨 관리

### 데이터 디렉토리

기본적으로 `./data` 디렉토리가 컨테이너의 `/app/data`에 마운트됩니다.

```bash
# 데이터 디렉토리 변경
export DATA_DIR=/path/to/your/data
make docker-up
```

### 개발 모드

개발 시 소스 코드가 read-only로 마운트되어 컨테이너 재시작 없이 변경사항을 반영할 수 있습니다.

```yaml
volumes:
  - ../app:/app/app:ro  # 소스 코드 (read-only)
  - mem-mesh-data:/app/data  # 데이터 (read-write)
```

## 프로덕션 배포

### 1. 환경변수 설정

`.env` 파일 생성:

```bash
cp .env.example .env
# .env 파일 편집
```

### 2. 이미지 빌드

```bash
make docker-build
```

### 3. 서비스 시작

```bash
make docker-up
```

### 4. 헬스 체크

```bash
make health-check
# 또는
curl http://localhost:8000/health
```

### 5. 로그 확인

```bash
make docker-logs-dashboard
```

## 문제 해결

### 포트 충돌

다른 포트 사용:

```yaml
# docker-compose.yml 수정
ports:
  - "9000:8000"  # 9000 포트로 변경
```

### 권한 문제

데이터 디렉토리 권한 확인:

```bash
chmod 755 ./data
chown -R 1000:1000 ./data
```

### 컨테이너 재시작

```bash
make docker-restart
```

### 완전 초기화

```bash
make docker-clean
make docker-build
make docker-up
```

## 모니터링

### 컨테이너 상태

```bash
docker compose -f docker/docker-compose.yml ps
```

### 리소스 사용량

```bash
docker stats mem-mesh-dashboard mem-mesh-mcp
```

### 로그 스트리밍

```bash
make docker-logs
```

## 보안 고려사항

1. **비밀번호 변경**: `.env` 파일의 기본 비밀번호를 변경하세요
2. **네트워크 격리**: 프로덕션에서는 외부 네트워크 노출을 최소화하세요
3. **볼륨 백업**: 정기적으로 데이터 볼륨을 백업하세요
4. **이미지 업데이트**: 정기적으로 베이스 이미지를 업데이트하세요

## 추가 정보

- [메인 README](../README.md)
- [설치 가이드](../SETUP.md)
- [API 문서](http://localhost:8000/docs)
