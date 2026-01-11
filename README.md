# mem-mesh

중앙 메모리 서버 - 벡터 검색과 맥락 조회를 지원하는 개발자용 메모리 관리 시스템

## 개요

mem-mesh는 개발자들이 작업 중 생성되는 다양한 메모리(작업, 버그, 아이디어, 결정사항 등)를 중앙에서 관리하고, 벡터 검색과 맥락 조회를 통해 효율적으로 활용할 수 있도록 도와주는 시스템입니다.

### 주요 기능

- **메모리 저장**: 텍스트 기반 메모리를 프로젝트별, 카테고리별로 저장
- **벡터 검색**: sentence-transformers를 사용한 의미 기반 검색
- **맥락 조회**: 특정 메모리와 관련된 시간순 맥락 정보 제공
- **MCP 통합**: Model Context Protocol을 통한 AI 도구 연동
- **REST API**: FastAPI 기반 웹 API 제공
- **중복 감지**: content hash를 통한 자동 중복 감지

## 빠른 시작

### 1. 설치

```bash
# 저장소 클론
git clone <repository-url>
cd mem-mesh

# 의존성 설치
pip install -r requirements.txt

# 또는 Poetry 사용
poetry install
```

### 2. 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# 필요에 따라 설정 수정
vim .env
```

### 3. 서버 실행

mem-mesh는 두 가지 모드로 실행할 수 있습니다:

#### MCP 서버 모드 (AI 도구 연동용)
```bash
# 기본 MCP 서버 실행
python -m src

# 또는 명시적으로 MCP 모드 지정
python -m src --mode mcp
```

#### FastAPI 서버 모드 (REST API 서버)
```bash
# 기본 FastAPI 서버 실행
python -m src --mode fastapi

# 커스텀 호스트/포트로 실행
python -m src --mode fastapi --host 0.0.0.0 --port 8080

# 개발 모드 (auto-reload)
python -m src --mode fastapi --reload

# 또는 직접 uvicorn 사용
uvicorn src.main:app --reload
```

#### 서버 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--mode` | 서버 모드 (mcp, fastapi) | mcp |
| `--host` | FastAPI 서버 호스트 | 127.0.0.1 |
| `--port` | FastAPI 서버 포트 | 8000 |
| `--reload` | 개발 모드 (auto-reload) | False |

### 4. 사용 예시

#### FastAPI 모드에서 REST API 사용

```bash
# 서버 시작
python -m src --mode fastapi

# 메모리 추가
curl -X POST "http://localhost:8000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Implemented user authentication with JWT tokens",
    "project_id": "my-app",
    "category": "task",
    "tags": ["auth", "jwt"]
  }'

# 메모리 검색
curl "http://localhost:8000/memories/search?query=authentication&project_id=my-app"

# 맥락 조회
curl "http://localhost:8000/memories/{memory_id}/context?depth=2"

# 통계 조회
curl "http://localhost:8000/memories/stats"

# 프로젝트별 통계
curl "http://localhost:8000/memories/stats?project_id=my-app"

# 날짜 범위별 통계
curl "http://localhost:8000/memories/stats?start_date=2024-01-01&end_date=2024-01-31"
```

#### MCP 모드에서 AI 도구 연동

MCP 모드로 실행하면 Cursor, Claude Desktop 등의 AI 도구에서 자연어로 메모리를 관리할 수 있습니다:

```bash
# MCP 서버 시작 (AI 도구에서 자동 실행)
python -m src --mode mcp
```

### MCP 사용 예제

mem-mesh를 AI 도구와 연동한 후 다음과 같은 자연어 명령으로 사용할 수 있습니다:

#### 📝 메모리 저장하기
```
"이 결정사항을 메모리에 저장해줘: 사용자 인증에 JWT 토큰 방식을 채택하기로 했다. 보안성과 확장성을 고려한 결정이다."

"버그를 발견했어. 메모리에 기록해줘: 로그인 페이지에서 특수문자가 포함된 비밀번호 입력 시 validation 에러가 발생한다. 프로젝트는 user-portal이야."

"아이디어를 저장하고 싶어: 사용자 대시보드에 실시간 알림 기능을 추가하면 어떨까? WebSocket을 사용해서 구현할 수 있을 것 같다."
```

#### 🔍 메모리 검색하기
```
"JWT 관련해서 이전에 저장한 내용들을 찾아줘"

"user-portal 프로젝트의 버그 관련 메모리들을 보여줘"

"지난주에 작업한 인증 관련 내용을 찾아줘"

"WebSocket이나 실시간 통신에 대한 아이디어가 있었나?"

"데이터베이스 최적화에 대한 결정사항들을 검색해줘"
```

#### 🔗 맥락 조회하기
```
"이 메모리 ID와 관련된 맥락을 보여줘: abc123-def456"

"방금 찾은 JWT 결정사항과 관련된 다른 메모리들도 보여줘"

"이 버그와 연관된 다른 이슈들이 있나?"
```

#### 📊 통계 및 관리
```
"현재 저장된 메모리 통계를 알려줘"

"user-portal 프로젝트의 메모리 현황을 보여줘"

"이번 달에 저장한 메모리들의 카테고리별 분포를 알려줘"

"작업 관련 메모리들을 업데이트해줘: 카테고리를 task에서 decision으로 변경"
```

#### 🚀 실제 워크플로우 예제

**1. 새 기능 개발 시작**
```
"새 기능 개발을 시작해. 메모리에 저장해줘: 사용자 프로필 편집 기능 개발 시작. React Hook Form과 Yup validation을 사용하기로 결정. 프로젝트는 user-dashboard."
```

**2. 개발 중 이슈 발견**
```
"버그를 발견했어: 프로필 이미지 업로드 시 파일 크기 제한이 제대로 작동하지 않는다. user-dashboard 프로젝트에 기록해줘."
```

**3. 해결책 아이디어 저장**
```
"아이디어 저장: 이미지 업로드 전에 클라이언트 사이드에서 파일 크기를 체크하고, 서버에서도 이중 검증하는 방식으로 개선하자."
```

**4. 관련 내용 검색**
```
"프로필 편집이나 이미지 업로드와 관련된 모든 메모리를 찾아줘"
```

**5. 프로젝트 회고**
```
"user-dashboard 프로젝트의 모든 결정사항들을 정리해서 보여줘"
```

#### 💡 효과적인 사용 팁

**구체적인 컨텍스트 제공:**
```
❌ "이거 저장해줘: 버그 있음"
✅ "로그인 API에서 버그 발견: 동시 로그인 시 세션 충돌 발생. auth-service 프로젝트에 저장해줘."
```

**프로젝트 ID 활용:**
```
✅ "user-portal 프로젝트의 인증 관련 이슈들을 모두 찾아줘"
✅ "e-commerce 프로젝트에 결정사항 저장: 결제 시스템으로 Stripe 채택"
```

**카테고리 명시:**
```
✅ "이 아이디어를 저장해줘: 사용자 경험 개선을 위한 다크모드 지원"
✅ "버그 리포트: 검색 기능에서 특수문자 처리 오류"
✅ "결정사항 기록: 코드 리뷰 프로세스에 자동화 도구 도입"
```

**태그 활용:**
```
✅ "성능 최적화 아이디어를 저장해줘. 태그는 performance, optimization, database로 설정"
```

## MCP 설정

mem-mesh를 AI 도구(Cursor, Claude Desktop 등)와 연동하려면 MCP 서버로 설정하세요.

**✅ MCP Protocol 완전 구현**: mem-mesh는 JSON-RPC 2.0 기반의 완전한 MCP protocol을 구현하여 timeout 없이 안정적으로 작동합니다.

### Cursor 설정

`.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "src", "--mode", "mcp"],
      "cwd": "/path/to/mem-mesh"
    }
  }
}
```

### Claude Desktop 설정

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "src", "--mode", "mcp"],
      "cwd": "/path/to/mem-mesh"
    }
  }
}
```

### Kiro 설정

`~/.kiro/settings/mcp.json`:
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "src", "--mode", "mcp"],
      "cwd": "/path/to/mem-mesh"
    }
  }
}
```

### 설정 참고사항

- `cwd`는 mem-mesh 프로젝트의 절대 경로로 설정하세요
- `--mode mcp`는 선택사항입니다 (기본값이 mcp)
- 기본 설정으로 `./data/memories.db`에 데이터베이스가 생성됩니다
- 필요시 `.env` 파일로 설정을 커스터마이징할 수 있습니다

### 독립 실행 vs MCP 연동

**독립 실행 (FastAPI 서버)**:
- REST API로 직접 접근
- 웹 브라우저에서 API 문서 확인 가능
- curl, Postman 등으로 테스트 가능

**MCP 연동**:
- AI 도구 내에서 직접 사용
- 자연어로 메모리 관리 가능
- 개발 워크플로우에 완전 통합

## 환경 변수

모든 환경 변수는 `MEM_MESH_` 접두사를 사용합니다.

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `MEM_MESH_DATABASE_PATH` | `./data/memories.db` | SQLite 데이터베이스 파일 경로 |
| `MEM_MESH_LOG_LEVEL` | `INFO` | 로그 레벨 (DEBUG, INFO, WARNING, ERROR) |
| `MEM_MESH_MIN_CONTENT_LENGTH` | `10` | 메모리 내용 최소 길이 |
| `MEM_MESH_MAX_CONTENT_LENGTH` | `10000` | 메모리 내용 최대 길이 |
| `MEM_MESH_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | 임베딩 모델명 |
| `MEM_MESH_EMBEDDING_DIM` | `384` | 임베딩 벡터 차원 |
| `MEM_MESH_SEARCH_THRESHOLD` | `0.5` | 검색 유사도 임계값 |
| `MEM_MESH_SERVER_HOST` | `127.0.0.1` | FastAPI 서버 호스트 |
| `MEM_MESH_SERVER_PORT` | `8000` | FastAPI 서버 포트 |

## 웹 UI

mem-mesh는 직관적인 웹 인터페이스를 제공하여 브라우저에서 메모리를 관리할 수 있습니다.

### 🌐 웹 UI 접속

FastAPI 서버 모드로 실행한 후 브라우저에서 접속하세요:

```bash
# FastAPI 서버 시작
python -m src --mode fastapi

# 브라우저에서 접속
# http://localhost:8000
```

### ✨ 주요 기능

#### 📊 대시보드
- 메모리 통계 및 최근 활동 현황
- 프로젝트별 메모리 분포 차트
- 카테고리별 통계 시각화
- 빠른 액션 버튼 (검색, 생성)

#### 🔍 검색 페이지
- 실시간 검색 (디바운싱 적용)
- 고급 필터링 (프로젝트, 카테고리, 날짜 범위)
- 검색 결과 하이라이팅
- 무한 스크롤 또는 페이지네이션

#### 📝 메모리 관리
- **메모리 생성**: 마크다운 지원, 실시간 미리보기
- **메모리 편집**: 인라인 편집, 변경사항 추적
- **메모리 상세**: 전체 내용, 메타데이터, 관련 메모리

#### 🔗 컨텍스트 시각화
- **타임라인 뷰**: 시간순 메모리 관계 표시
- **네트워크 그래프**: 메모리 간 연결 관계 시각화
- **관련 메모리**: 유사도 기반 추천

#### 📁 프로젝트 관리
- 프로젝트별 메모리 현황
- 프로젝트 통계 및 활동 타임라인
- 데이터 내보내기 (JSON, CSV)

#### 📈 분석 대시보드
- 메모리 생성 추이 차트
- 생산성 패턴 분석 (시간대별, 요일별)
- 단어 빈도 분석 및 워드 클라우드
- 카테고리 분포 및 태그 사용 현황

### ⌨️ 키보드 단축키

| 단축키 | 기능 |
|--------|------|
| `Ctrl+K` | 검색 페이지로 이동 |
| `Ctrl+N` | 새 메모리 생성 |
| `Ctrl+H` | 대시보드로 이동 |
| `Ctrl+P` | 프로젝트 페이지로 이동 |
| `Ctrl+A` | 분석 페이지로 이동 |
| `Ctrl+T` | 다크/라이트 테마 전환 |
| `Ctrl+/` | 키보드 단축키 도움말 |
| `Escape` | 모달 닫기 |
| `J/K` | 목록에서 위/아래 이동 |
| `Enter` | 선택된 항목 활성화 |

### 🎨 테마 지원

- **라이트 테마**: 밝은 배경의 기본 테마
- **다크 테마**: 어두운 배경의 다크 모드
- **자동 전환**: 시스템 설정에 따른 자동 테마 전환
- **사용자 설정 저장**: 로컬 스토리지에 테마 설정 저장

### 📱 반응형 디자인

- **데스크톱**: 전체 기능 지원, 멀티 컬럼 레이아웃
- **태블릿**: 적응형 레이아웃, 터치 최적화
- **모바일**: 모바일 우선 디자인, 스와이프 제스처

### 🚀 성능 최적화

- **가상 스크롤링**: 대용량 메모리 목록 최적화
- **지연 로딩**: 이미지 및 컴포넌트 지연 로딩
- **캐싱**: API 응답 캐싱 및 캐시 무효화
- **압축**: Gzip 압축 지원
- **PWA 지원**: 오프라인 사용 가능

### 🧪 테스트

웹 UI 테스트를 실행하려면:

```bash
# 테스트 페이지 접속
# http://localhost:8000/test-runner.html

# 또는 Python 빌드 스크립트 실행
python build.py
```

### 🔧 개발 모드

개발 중에는 다음과 같이 실행하세요:

```bash
# 개발 서버 시작 (auto-reload)
python -m src --mode fastapi --reload

# 또는 직접 uvicorn 사용
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 📦 프로덕션 배포

```bash
# 빌드 스크립트 실행
python build.py

# 빌드된 파일은 dist/ 디렉토리에 생성됩니다
# - 압축된 CSS/JS 파일
# - 캐시 버스팅을 위한 해시 파일명
# - Service Worker (오프라인 지원)
# - 성능 최적화된 HTML
```

### 🌟 웹 UI 특징

- **Web Components**: 재사용 가능한 커스텀 엘리먼트
- **Vanilla JavaScript**: 프레임워크 없는 가벼운 구현
- **모듈 시스템**: ES6 모듈 기반 코드 구조
- **접근성**: ARIA 라벨 및 키보드 네비게이션 지원
- **국제화**: 다국어 지원 준비 (현재 한국어/영어)

## API 문서

서버 실행 후 다음 URL에서 API 문서를 확인할 수 있습니다:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 주요 엔드포인트

- `POST /memories` - 메모리 추가
- `GET /memories/search` - 메모리 검색
- `GET /memories/{id}/context` - 맥락 조회
- `GET /memories/stats` - 메모리 통계 조회
- `PUT /memories/{id}` - 메모리 업데이트
- `DELETE /memories/{id}` - 메모리 삭제

## MCP 도구

mem-mesh는 다음 MCP 도구들을 제공합니다:

### 📝 mem-mesh.add
새 메모리를 추가합니다.
- **필수 파라미터**: `content` (10-10000자)
- **선택 파라미터**: `project_id`, `category`, `source`, `tags`
- **카테고리**: task, bug, idea, decision, incident, code_snippet

### 🔍 mem-mesh.search  
벡터 검색과 메타데이터 필터링을 통해 메모리를 검색합니다.
- **필수 파라미터**: `query` (3자 이상)
- **선택 파라미터**: `project_id`, `category`, `limit` (1-20), `recency_weight` (0.0-1.0)

### 🔗 mem-mesh.context
특정 메모리와 관련된 맥락 정보를 조회합니다.
- **필수 파라미터**: `memory_id`
- **선택 파라미터**: `depth` (1-5), `project_id`

### 📊 mem-mesh.stats
저장된 메모리의 통계 정보를 조회합니다.
- **선택 파라미터**: `project_id`, `start_date`, `end_date`, `group_by`

### ✏️ mem-mesh.update
기존 메모리를 업데이트합니다.
- **필수 파라미터**: `memory_id`
- **선택 파라미터**: `content`, `category`, `tags`

### 🗑️ mem-mesh.delete
메모리를 삭제합니다.
- **필수 파라미터**: `memory_id`

## 사용 시나리오

### 🎯 개발팀 지식 관리
- **기술 결정사항 기록**: "마이크로서비스 간 통신에 gRPC 채택 결정"
- **버그 트래킹**: "결제 모듈에서 동시성 이슈 발견, 락 메커니즘 필요"
- **아키텍처 아이디어**: "Redis 클러스터링으로 캐시 성능 개선 방안"

### 📚 개인 학습 노트
- **학습 내용 정리**: "Kubernetes Pod 생명주기와 리소스 관리 방법"
- **코드 스니펫 저장**: "JWT 토큰 검증 미들웨어 구현 코드"
- **문제 해결 과정**: "Docker 컨테이너 메모리 누수 디버깅 과정"

### 🔄 프로젝트 히스토리
- **마일스톤 기록**: "v2.0 릴리즈 완료, 사용자 피드백 긍정적"
- **회고 내용**: "스프린트 리뷰에서 나온 프로세스 개선 아이디어들"
- **레슨런**: "배포 자동화 도입으로 에러율 50% 감소"

### 🤝 팀 협업
- **회의 결과**: "API 설계 리뷰 미팅에서 REST → GraphQL 전환 논의"
- **코드 리뷰 피드백**: "성능 최적화를 위한 데이터베이스 인덱스 추가 제안"
- **온보딩 가이드**: "신입 개발자를 위한 개발 환경 설정 가이드"

## 개발

### 테스트 실행

```bash
# 모든 테스트 실행
pytest

# 특정 테스트 파일 실행
pytest tests/test_memory_service.py

# 커버리지 포함
pytest --cov=src
```

### 코드 품질

```bash
# 린팅
flake8 src tests

# 타입 체크
mypy src

# 포맷팅
black src tests
```

## 아키텍처

```
src/
├── config.py              # 설정 관리
├── main.py                # FastAPI 앱
├── __main__.py            # MCP 서버 진입점
├── database/
│   ├── base.py            # 데이터베이스 연결
│   └── models.py          # 데이터 모델
├── embeddings/
│   └── service.py         # 임베딩 서비스
├── mcp/
│   ├── server.py          # MCP 서버
│   └── tools.py           # MCP 도구들
├── schemas/
│   ├── requests.py        # 요청 스키마
│   └── responses.py       # 응답 스키마
├── services/
│   ├── memory.py          # 메모리 CRUD
│   ├── search.py          # 검색 서비스
│   └── context.py         # 맥락 서비스
└── utils/
    └── logger.py          # 로깅 유틸리티
```

## 기술 스택

- **Backend**: Python 3.8+, FastAPI
- **Database**: SQLite + sqlite-vec (벡터 검색)
- **Embeddings**: sentence-transformers
- **Protocol**: Model Context Protocol (MCP)
- **Testing**: pytest, httpx

## 라이선스

MIT License

## 기여

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 지원

문제가 있거나 질문이 있으시면 GitHub Issues를 통해 문의해 주세요.