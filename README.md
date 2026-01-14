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
- **이중 아키텍처**: Direct SQLite 접근과 API 모드 지원
- **동시성 지원**: SQLite WAL 모드를 통한 안전한 동시 접근

## 🚀 새로운 아키텍처 (v2.0)

mem-mesh v2.0은 완전히 재설계된 아키텍처를 제공합니다:

### 📁 디렉토리 구조
```
mem-mesh/
├── app/                    # 새로운 애플리케이션 디렉토리
│   ├── mcp/               # FastMCP 기반 MCP 서버
│   ├── dashboard/         # FastAPI 대시보드
│   └── core/              # 공통 모듈 (database, services, storage)
├── src/                   # 기존 코드 (하위 호환성)
└── static/                # 웹 UI 정적 파일
```

### 🔄 스토리지 모드
mem-mesh는 이제 두 가지 스토리지 모드를 지원합니다:

- **Direct 모드**: MCP 서버가 SQLite에 직접 접근 (기본값)
- **API 모드**: MCP 서버가 FastAPI를 통해 데이터에 접근

### ⚡ FastMCP 기반 구현
- 기존 MCP 구현 대비 더 간결하고 유지보수하기 쉬운 코드
- 데코레이터 기반 도구 정의
- 향상된 에러 처리 및 로깅

## 🚀 실행 가이드

### 1. 기본 설정

```bash
# 프로젝트 클론
git clone https://github.com/JINWOO-J/mem-mesh
cd mem-mesh

# 의존성 설치 (개발 의존성 포함)
pip install -e ".[dev]"

# 또는 기본 의존성만
pip install -e .

# 또는 requirements.txt 사용
pip install -r requirements.txt

# 환경 설정
cp .env.example .env
```

**중요 의존성:**
- `pysqlite3`: 향상된 SQLite 성능과 기능을 위해 필수
- `sentence-transformers`: 벡터 검색을 위한 임베딩 생성
- `sse-starlette`: SSE MCP 지원을 위해 필요

### 2. 실행 모드 선택

#### 🆕 새로운 통합 아키텍처 (권장)

**웹 서버 실행 (통합 모드):**
```bash
# 웹 대시보드와 SSE MCP를 함께 제공
python -m app.web --reload

# 커스텀 호스트/포트로 실행
python -m app.web --host 0.0.0.0 --port 8080

# 프로덕션 환경 (멀티 워커)
python -m app.web --workers 4

# 브라우저에서 접속: http://localhost:8000
# SSE MCP 엔드포인트: http://localhost:8000/mcp/sse
```

**Stdio MCP 서버 (AI 도구 연동용):**
```bash
# FastMCP 기반 MCP 서버
python -m app.mcp_stdio

# 순수 MCP 프로토콜 구현 (더 안정적)
python -m app.mcp_stdio_pure
```

#### 🔄 기존 아키텍처 (하위 호환성)

**Direct 모드 (기본값):**
```bash
# MCP 서버만 실행
python -m app.mcp

# 또는 명시적으로 Direct 모드 지정
MEM_MESH_STORAGE_MODE=direct python -m app.mcp
```

**API 모드:**
```bash
# 1단계: FastAPI 대시보드 시작
MEM_MESH_SERVER_PORT=8002 python -m app.dashboard

# 2단계: API 모드로 MCP 서버 시작
MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 python -m app.mcp
```

### 3. 🌐 SSE MCP 사용법

mem-mesh는 HTTP 기반의 SSE (Server-Sent Events) MCP transport를 지원합니다.

#### SSE MCP 서버 시작
```bash
# 웹 서버 + SSE MCP 통합 실행
python -m app.web --reload

# SSE MCP 엔드포인트 확인
curl http://localhost:8000/mcp/info
```

#### SSE MCP 엔드포인트

**1. 서버 정보 조회**
```bash
GET /mcp/info
```

**2. SSE 스트림 연결**
```bash
GET /mcp/sse
# 세션 ID를 받고 실시간 메시지 수신
```

**3. 메시지 전송 (세션 기반)**
```bash
POST /mcp/message?session_id={session_id}
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

**4. 단일 요청-응답**
```bash
POST /mcp/sse
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "add",
    "arguments": {
      "content": "SSE MCP 테스트 메모리",
      "project_id": "sse-test",
      "category": "task"
    }
  }
}
```

#### SSE MCP 클라이언트 예제

**JavaScript 클라이언트:**
```javascript
// SSE 연결
const eventSource = new EventSource('/mcp/sse');
let sessionEndpoint = null;

eventSource.addEventListener('endpoint', (event) => {
  sessionEndpoint = event.data;
  console.log('Session endpoint:', sessionEndpoint);
});

eventSource.addEventListener('message', (event) => {
  const response = JSON.parse(event.data);
  console.log('MCP Response:', response);
});

// 메시지 전송
async function sendMCPRequest(request) {
  if (!sessionEndpoint) {
    throw new Error('Session not established');
  }
  
  const response = await fetch(sessionEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });
  
  return response.json();
}

// 사용 예시
sendMCPRequest({
  jsonrpc: "2.0",
  id: 1,
  method: "tools/call",
  params: {
    name: "search",
    arguments: { query: "JavaScript", limit: 5 }
  }
});
```

**Python 클라이언트:**
```python
import requests
import json

# 단일 요청-응답 방식
def call_sse_mcp(method, params=None):
    url = "http://localhost:8000/mcp/sse"
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    
    response = requests.post(url, json=request)
    return response.json()

# 사용 예시
result = call_sse_mcp("tools/list")
print("Available tools:", result)

result = call_sse_mcp("tools/call", {
    "name": "add",
    "arguments": {
        "content": "Python SSE MCP 테스트",
        "category": "task"
    }
})
print("Add result:", result)
```

### 4. 🔧 로깅 시스템

mem-mesh는 중앙 집중식 로깅 시스템을 제공합니다.

#### 환경변수 설정
```bash
# 로그 레벨 설정
export MCP_LOG_LEVEL="DEBUG"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# 파일 로깅 활성화
export MCP_LOG_FILE="./logs/mem-mesh.log"

# 로그 형식 설정
export MCP_LOG_FORMAT="text"  # text 또는 json
```

#### 로깅 사용 예시
```bash
# 파일 로깅과 함께 웹 서버 실행
MCP_LOG_FILE=./logs/mem-mesh.log MCP_LOG_LEVEL=DEBUG python -m app.web --reload

# 로그 파일 실시간 확인
tail -f ./logs/mem-mesh.log

# JSON 형식 로깅
MCP_LOG_FORMAT=json MCP_LOG_FILE=./logs/mem-mesh.json python -m app.web --reload
```

### 3. AI 도구 연동

#### Kiro 연동
```bash
# ~/.kiro/settings/mcp.json 파일 생성/수정
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/절대/경로/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO",
        "MCP_LOG_FILE": "./logs/mem-mesh-kiro.log"
      }
    }
  }
}
```

#### Claude Desktop 연동
```bash
# ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio_pure"],
      "cwd": "/절대/경로/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

#### Cursor 연동
```bash
# .cursor/mcp.json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/절대/경로/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "DEBUG",
        "MCP_LOG_FILE": "./logs/mem-mesh-cursor.log"
      }
    }
  }
}
```

#### SSE MCP 연동 (웹 기반 AI 도구)
```bash
# 웹 서버 실행
python -m app.web --reload

# SSE MCP 엔드포인트 사용
# GET  http://localhost:8000/mcp/sse      - SSE 스트림 연결
# POST http://localhost:8000/mcp/message - 메시지 전송
# POST http://localhost:8000/mcp/sse     - 단일 요청-응답
# GET  http://localhost:8000/mcp/info    - 서버 정보
```

### 4. 테스트 및 검증

```bash
# 자동화된 테스트 실행
python simple_test.py

# SSE MCP 테스트
curl -X POST http://localhost:8000/mcp/sse \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# 웹 서버 + SSE MCP 통합 테스트
python -m app.web --reload &
sleep 2
curl http://localhost:8000/mcp/info

# SSE MCP 도구 호출 테스트
curl -X POST http://localhost:8000/mcp/sse \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "add",
      "arguments": {
        "content": "SSE MCP 테스트 메모리",
        "category": "task",
        "project_id": "sse-test"
      }
    }
  }'

# 전체 테스트 스위트
pytest

# 속성 기반 테스트
pytest tests/test_properties.py

# 로깅 시스템 테스트
MCP_LOG_FILE=./logs/test.log MCP_LOG_LEVEL=DEBUG python test_logging_example.py

# 조건부 로깅 테스트
python test_conditional_logging.py
```

### 5. 문제 해결

**포트 충돌:**
```bash
# 사용 중인 포트 확인
lsof -i :8000

# 다른 포트 사용
python -m app.web --port 8080
```

**로깅 문제:**
```bash
# 로그 파일이 생성되지 않는 경우
mkdir -p logs
MCP_LOG_FILE=./logs/mem-mesh.log python -m app.web --reload

# 로그 레벨 확인
MCP_LOG_LEVEL=DEBUG python -m app.web --reload
```

**SSE MCP 연결 문제:**
```bash
# SSE 엔드포인트 확인
curl http://localhost:8000/mcp/info

# CORS 문제 시 (개발 환경)
# 브라우저에서 --disable-web-security 플래그 사용
```

**sqlite-vec 경고:**
```
sqlite-vec available with sqlite3 but extension loading not supported
```
이 경고는 무시해도 됩니다. 시스템이 자동으로 fallback 검색을 사용합니다.

**MCP 연결 문제:**
- `cwd` 경로가 절대 경로인지 확인
- Python 환경이 올바른지 확인
- 의존성이 설치되었는지 확인
- 로그 파일을 확인하여 오류 메시지 분석

## 빠른 시작

### 1. 설치

```bash
# 저장소 클론
git clone https://github.com/JINWOO-J/mem-mesh
cd mem-mesh

# 의존성 설치 (개발 의존성 포함)
pip install -e ".[dev]"

# 또는 기본 의존성만
pip install -e .

# 또는 requirements.txt 사용
pip install -r requirements.txt
```

**필수 의존성 참고:**
- **pysqlite3**: SQLite 성능 향상을 위해 필수 설치
- **fastmcp**: 새로운 MCP 서버 아키텍처를 위해 필요
- **sentence-transformers**: 벡터 검색 기능을 위한 임베딩 생성

**설치 문제 해결:**
```bash
# pysqlite3 설치 문제 시
pip install pysqlite3-binary

# macOS에서 컴파일 문제 시
brew install sqlite3
pip install pysqlite3
```

### 2. 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# 필요에 따라 설정 수정
vim .env
```

### 3. 서버 실행

#### 🆕 새로운 아키텍처 (권장)

**FastMCP 기반 MCP 서버 (Direct 모드)**
```bash
# Direct 모드로 MCP 서버 실행 (기본값)
python -m app.mcp

# 또는 명시적으로 Direct 모드 지정
MEM_MESH_STORAGE_MODE=direct python -m app.mcp
```

**FastMCP 기반 MCP 서버 (API 모드)**
```bash
# 먼저 FastAPI 대시보드 실행
python -m app.dashboard

# 다른 터미널에서 API 모드로 MCP 서버 실행
MEM_MESH_STORAGE_MODE=api python -m app.mcp
```

**FastAPI 대시보드**
```bash
# 대시보드 실행
python -m app.dashboard

# 커스텀 호스트/포트로 실행
MEM_MESH_SERVER_HOST=0.0.0.0 MEM_MESH_SERVER_PORT=8080 python -m app.dashboard
```

#### 🔄 기존 아키텍처 (하위 호환성)

**기존 MCP 서버**
```bash
# 기본 MCP 서버 실행
python -m src

# 또는 명시적으로 MCP 모드 지정
python -m src --mode mcp
```

**기존 FastAPI 서버**
```bash
# FastAPI 서버 실행
python -m src --mode fastapi

# 개발 모드 (auto-reload)
python -m src --mode fastapi --reload
```

### 4. 🧪 MCP 기능 테스트

#### 방법 1: 직접 테스트 (stdio)

**Direct 모드 테스트:**
```bash
# MCP 서버 시작 (Direct 모드)
python -m app.mcp

# 다른 터미널에서 JSON-RPC 메시지 전송
echo '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}}' | python -m app.mcp
```

**API 모드 테스트:**
```bash
# 1. FastAPI 대시보드 시작
MEM_MESH_SERVER_PORT=8002 python -m app.dashboard

# 2. 다른 터미널에서 API 모드로 MCP 서버 시작
MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 python -m app.mcp

# 3. 다른 터미널에서 테스트
echo '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}}' | MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 python -m app.mcp
```

#### 방법 2: 자동화된 테스트 스크립트

**Direct 모드 테스트:**
```bash
# 포함된 테스트 스크립트 실행
python simple_test.py
```

**API 모드 테스트:**
```bash
# FastAPI 대시보드 먼저 시작
MEM_MESH_SERVER_PORT=8002 python -m app.dashboard &

# API 모드 테스트 실행
python test_api_mode.py
```

#### 방법 3: MCP Inspector 사용

```bash
# MCP Inspector 설치
npm install -g @modelcontextprotocol/inspector

# Direct 모드 검사
mcp-inspector python -m app.mcp

# API 모드 검사 (FastAPI 대시보드가 실행 중이어야 함)
MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 mcp-inspector python -m app.mcp
```

#### 방법 4: AI 도구 연동 테스트

**Cursor 설정** (`.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct"
      }
    }
  }
}
```

**Claude Desktop 설정** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct"
      }
    }
  }
}
```

**Kiro 설정** (`~/.kiro/settings/mcp.json`):
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct"
      }
    }
  }
}
```

#### 🧪 테스트 결과 확인

**성공적인 테스트 출력 예시:**
```
🚀 MCP 서버 테스트 시작...
✅ 서버 시작됨: Starting MCP server in direct mode
✅ 초기화 성공!
✅ 사용 가능한 도구 수: 6
   - add: Add a new memory to the memory store
   - search: Search memories using hybrid search
   - context: Get context around a specific memory
   - update: Update an existing memory
   - delete: Delete a memory from the store
   - stats: Get statistics about stored memories
✅ 메모리 추가 성공! ID: 49eb34a1-2cae-4f9e-99af-e4d1c0b48951
✅ 통계 조회 성공!
🎉 MCP 서버 테스트 완료!
```

#### 🔧 문제 해결

**포트 충돌 해결:**
```bash
# 사용 중인 포트 확인
lsof -i :8000

# 다른 포트 사용
MEM_MESH_SERVER_PORT=8002 python -m app.dashboard
```

**sqlite-vec 경고 무시:**
```
sqlite-vec available with sqlite3 but extension loading not supported
```
이 경고는 무시해도 됩니다. 시스템이 자동으로 fallback 텍스트 검색을 사용합니다.

### 5. 사용 예시

#### 🆕 새로운 FastMCP 서버 테스트

**Direct 모드 테스트:**
```bash
# 1. MCP 서버 시작 (Direct 모드)
python -m app.mcp

# 2. 다른 터미널에서 도구 목록 확인
echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' | python -m app.mcp

# 3. 메모리 추가 테스트
echo '{
  "jsonrpc": "2.0", 
  "id": 2, 
  "method": "tools/call",
  "params": {
    "name": "add",
    "arguments": {
      "content": "FastMCP 기반 MCP 서버 테스트 중입니다",
      "project_id": "mem-mesh-test",
      "category": "task",
      "tags": ["test", "fastmcp"]
    }
  }
}' | python -m app.mcp

# 4. 메모리 검색 테스트
echo '{
  "jsonrpc": "2.0", 
  "id": 3, 
  "method": "tools/call",
  "params": {
    "name": "search",
    "arguments": {
      "query": "FastMCP 테스트",
      "limit": 5
    }
  }
}' | python -m app.mcp

# 5. 통계 조회 테스트
echo '{
  "jsonrpc": "2.0", 
  "id": 4, 
  "method": "tools/call",
  "params": {
    "name": "stats",
    "arguments": {}
  }
}' | python -m app.mcp
```

**API 모드 테스트:**
```bash
# 1. FastAPI 대시보드 시작
MEM_MESH_SERVER_PORT=8002 python -m app.dashboard

# 2. 다른 터미널에서 API 모드로 MCP 서버 시작 및 테스트
MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 python -m app.mcp

# 3. 메모리 추가 테스트 (API 모드)
echo '{
  "jsonrpc": "2.0", 
  "id": 1, 
  "method": "tools/call",
  "params": {
    "name": "add",
    "arguments": {
      "content": "API 모드에서 MCP 서버 테스트 중입니다",
      "project_id": "api-mode-test",
      "category": "task",
      "tags": ["api-mode", "test"]
    }
  }
}' | MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 python -m app.mcp
```

#### FastAPI 대시보드 테스트

```bash
# 1. 대시보드 시작
MEM_MESH_SERVER_PORT=8002 python -m app.dashboard

# 2. 브라우저에서 접속
# http://localhost:8002

# 3. API 문서 확인
# http://localhost:8002/docs

# 4. REST API 테스트
curl -X POST "http://localhost:8002/api/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "새로운 아키텍처 테스트 중입니다",
    "project_id": "mem-mesh-v2",
    "category": "task",
    "tags": ["architecture", "test"]
  }'

# 5. 검색 테스트
curl "http://localhost:8002/api/memories/search?query=아키텍처&limit=5"

# 6. 통계 조회
curl "http://localhost:8002/api/memories/stats"
```

#### API 모드 완전 테스트

```bash
# 1. FastAPI 대시보드 시작
MEM_MESH_SERVER_PORT=8002 python -m app.dashboard

# 2. 다른 터미널에서 API 모드로 MCP 서버 시작
MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 python -m app.mcp

# 3. 세 번째 터미널에서 MCP 서버가 FastAPI를 통해 데이터에 접근하는지 확인
echo '{
  "jsonrpc": "2.0", 
  "id": 1, 
  "method": "tools/call",
  "params": {
    "name": "add",
    "arguments": {
      "content": "API 모드 테스트 중입니다",
      "project_id": "api-mode-test",
      "category": "task"
    }
  }
}' | MEM_MESH_STORAGE_MODE=api MEM_MESH_API_BASE_URL=http://localhost:8002 python -m app.mcp
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

## 🔧 개발 도구

mem-mesh는 임베딩 모델 최적화와 검색 품질 향상을 위한 다양한 개발 도구를 제공합니다.

### 🔍 대화형 검색 도구

실시간으로 다양한 임베딩 모델을 전환하며 검색 결과를 확인할 수 있는 대화형 도구입니다.

```bash
# 기본 실행
python scripts/interactive_search.py

# 검색어와 함께 바로 실행
python scripts/interactive_search.py "버그 수정"

# 상세 로그와 함께 실행
python scripts/interactive_search.py -v

# 특정 모델로 시작
python scripts/interactive_search.py --model all-mpnet-base-v2

# 모든 옵션 조합
python scripts/interactive_search.py "API 구현" --model all-mpnet-base-v2 --limit 10 --category decision
```

**주요 기능:**
- 명령행에서 바로 검색어 입력 가능
- 실시간 모델 전환 및 성능 비교
- 다양한 검색 필터 (프로젝트, 카테고리)
- 상세한 검색 결과 표시
- 사용자 친화적인 대화형 인터페이스

**사용 예시:**
```
# 명령행에서 바로 검색
python scripts/interactive_search.py "버그 수정"

# 대화형 모드에서 계속 사용
search(multilingual-e5-small, limit=5)> models
search(multilingual-e5-small, limit=5)> model all-mpnet-base-v2
search(all-mpnet-base-v2, limit=5)> search API 구현
search(all-mpnet-base-v2, limit=5) [category:decision]> search 아키텍처
```

### 📊 임베딩 모델 테스트 도구

검색 품질 향상을 위한 종합적인 임베딩 모델 테스트 시스템:

```bash
# 종합 벤치마크
python scripts/benchmark_embedding_models.py

# A/B 테스트
python scripts/ab_test_embeddings.py all-MiniLM-L6-v2 all-mpnet-base-v2

# 검색 품질 평가
python scripts/evaluate_search_quality.py --models all-MiniLM-L6-v2 all-mpnet-base-v2

# 모델 전환
python scripts/switch_embedding_model.py intfloat/multilingual-e5-base
```

자세한 사용법은 [임베딩 모델 테스트 가이드](docs/embedding_model_testing_guide.md)를 참조하세요.

## MCP 설정

mem-mesh를 AI 도구(Cursor, Claude Desktop 등)와 연동하려면 MCP 서버로 설정하세요.

**✅ MCP Protocol 완전 구현**: mem-mesh는 JSON-RPC 2.0 기반의 완전한 MCP protocol을 구현하여 timeout 없이 안정적으로 작동합니다.

### 🆕 새로운 통합 아키텍처 설정 (권장)

#### 🚀 Stdio MCP 서버 (AI 도구 연동용)

**FastMCP 기반 서버 (권장):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO",
        "MCP_LOG_FILE": "./logs/mem-mesh-mcp.log"
      }
    }
  }
}
```

**순수 MCP 프로토콜 구현 (더 안정적):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio_pure"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO",
        "MCP_LOG_FILE": "./logs/mem-mesh-pure.log"
      }
    }
  }
}
```

#### 🌐 SSE MCP (웹 기반 AI 도구용)

웹 기반 AI 도구나 브라우저 환경에서는 SSE MCP를 사용할 수 있습니다:

```bash
# 웹 서버 + SSE MCP 실행
python -m app.web --reload

# SSE MCP 엔드포인트
# GET  http://localhost:8000/mcp/sse      - SSE 스트림 연결
# POST http://localhost:8000/mcp/message - 메시지 전송 (세션 기반)
# POST http://localhost:8000/mcp/sse     - 단일 요청-응답
# GET  http://localhost:8000/mcp/info    - 서버 정보
```

**mcp.json에서 SSE MCP 설정 (실험적):**

⚠️ **주의**: 대부분의 MCP 클라이언트는 stdio transport만 지원합니다. SSE MCP는 웹 기반 도구나 커스텀 클라이언트에서 주로 사용됩니다.

```json
{
  "mcpServers": {
    "mem-mesh-sse": {
      "command": "python",
      "args": ["-c", "import requests; import sys; import json; req=json.load(sys.stdin); print(json.dumps(requests.post('http://localhost:8000/mcp/sse', json=req).json()))"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MCP_TRANSPORT": "http-sse"
      }
    }
  }
}
```

**권장사항**: 일반적인 AI 도구 연동에는 **Stdio MCP 서버**를 사용하세요:
- Kiro, Claude Desktop, Cursor 등: `python -m app.mcp_stdio`
- 웹 기반 도구, 브라우저: SSE MCP 엔드포인트 직접 사용

**🔧 mcp.json에서 SSE MCP 설정:**

SSE MCP는 HTTP transport를 사용하므로 일반적인 MCP 클라이언트에서는 직접 지원되지 않을 수 있습니다. 하지만 HTTP 요청을 지원하는 AI 도구에서는 다음과 같이 설정할 수 있습니다:

```json
{
  "mcpServers": {
    "mem-mesh-sse": {
      "command": "curl",
      "args": [
        "-X", "POST",
        "http://localhost:8000/mcp/sse",
        "-H", "Content-Type: application/json",
        "-d", "@-"
      ],
      "env": {
        "MCP_TRANSPORT": "http-sse"
      }
    }
  }
}
```

**⚠️ 주의사항:**
- SSE MCP 사용 전에 웹 서버가 실행되어 있어야 합니다: `python -m app.web --reload`
- 대부분의 MCP 클라이언트는 stdio transport를 기본으로 하므로, SSE MCP는 웹 기반 도구나 커스텀 클라이언트에서 주로 사용됩니다
- 일반적인 AI 도구 연동에는 **Stdio MCP 서버**를 권장합니다

**SSE MCP 사용 예시:**
```javascript
// JavaScript에서 SSE MCP 사용
const eventSource = new EventSource('http://localhost:8000/mcp/sse');
eventSource.addEventListener('message', (event) => {
  const response = JSON.parse(event.data);
  console.log('MCP Response:', response);
});

// 메시지 전송
fetch('http://localhost:8000/mcp/sse', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: {
      name: "search",
      arguments: { query: "JavaScript", limit: 5 }
    }
  })
});
```

**Python 클라이언트:**
```python
import requests
import json

# 단일 요청-응답 방식
def call_sse_mcp(method, params=None):
    url = "http://localhost:8000/mcp/sse"
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    
    response = requests.post(url, json=request)
    return response.json()

# 사용 예시
result = call_sse_mcp("tools/list")
print("Available tools:", result)

result = call_sse_mcp("tools/call", {
    "name": "add",
    "arguments": {
        "content": "Python SSE MCP 테스트",
        "category": "task"
    }
})
print("Add result:", result)
```

**SSE MCP 사용 예시:**
```javascript
// JavaScript에서 SSE MCP 사용
const eventSource = new EventSource('http://localhost:8000/mcp/sse');
eventSource.addEventListener('message', (event) => {
  const response = JSON.parse(event.data);
  console.log('MCP Response:', response);
});

// 메시지 전송
fetch('http://localhost:8000/mcp/sse', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: {
      name: "search",
      arguments: { query: "JavaScript", limit: 5 }
    }
  })
});
```

### 🔧 AI 도구별 설정

#### Claude Desktop 설정

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

**Stdio MCP (권장):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio_pure"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

**SSE MCP (실험적):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "sse": {
        "url": "http://localhost:8000/sse"
      }
    }
  }
}
```

#### Cursor 설정

`.cursor/mcp.json`:

**Stdio MCP (권장):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "DEBUG",
        "MCP_LOG_FILE": "./logs/mem-mesh-cursor.log"
      }
    }
  }
}
```

**SSE MCP (실험적):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "url": "http://localhost:8000/mcp/sse"
    }
  }
}
```

#### Kiro, Gemini, Qwen 설정

`~/.kiro/settings/mcp.json`, `.gemini/settings.json`, `.qwen____/settings.json`:

**Stdio MCP (권장):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO",
        "MCP_LOG_FILE": "./logs/mem-mesh-kiro.log"
      }
    }
  }
}
```

**SSE MCP (실험적):**
```json
{
  "mcpServers": {
    "mem-mesh": {
      "url": "http://localhost:8000/mcp/sse",
      "transport": "sse"
    }
  }
}
```

### 🔄 기존 MCP 설정 (하위 호환성)

#### 🔧 SSL 검증 우회 (네트워크 환경 문제 시)

일부 네트워크 환경에서 SSL 인증서 검증 문제가 발생할 수 있습니다. 이 경우 `MEM_MESH_IGNORE_SSL` 환경변수를 사용하여 SSL 검증을 우회할 수 있습니다:

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.pure_mcp"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct",
        "MEM_MESH_IGNORE_SSL": "1"
      }
    }
  }
}
```

**⚠️ 보안 주의사항**: `MEM_MESH_IGNORE_SSL=1`은 SSL 인증서 검증을 완전히 비활성화합니다. 신뢰할 수 있는 네트워크 환경에서만 사용하세요.

#### Cursor 설정

`.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct"
      }
    }
  }
}
```

#### Claude Desktop 설정

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct"
      }
    }
  }
}
```

#### Kiro 설정

`~/.kiro/settings/mcp.json`:
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct"
      }
    }
  }
}
```

### 설정 참고사항

- `cwd`는 mem-mesh 프로젝트의 절대 경로로 설정하세요
- **새로운 아키텍처**: 
  - `python -m app.mcp_stdio` (FastMCP 기반, 권장)
  - `python -m app.mcp_stdio_pure` (순수 MCP 구현, 더 안정적)
  - `python -m app.web --reload` (웹 서버 + SSE MCP)
- **기존 아키텍처**: `python -m src --mode mcp` (하위 호환성)
- 기본 설정으로 `./data/memories.db`에 데이터베이스가 생성됩니다
- 로깅 설정으로 디버깅과 모니터링이 가능합니다
- 필요시 `.env` 파일로 설정을 커스터마이징할 수 있습니다

### MCP Transport 방식

#### 🔌 Stdio Transport (권장)
- **사용 도구**: Kiro, Claude Desktop, Cursor 등 대부분의 MCP 클라이언트
- **설정 방법**: `command`와 `args`로 실행 파일 지정
- **통신 방식**: stdin/stdout을 통한 JSON-RPC
- **장점**: 표준 MCP 프로토콜, 안정적, 널리 지원됨

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh"
    }
  }
}
```

#### 🌐 HTTP SSE Transport (실험적)
- **사용 도구**: 웹 기반 AI 도구, 브라우저, 커스텀 클라이언트
- **설정 방법**: HTTP 엔드포인트 직접 호출
- **통신 방식**: HTTP POST + Server-Sent Events
- **장점**: 웹 환경에서 사용 가능, 방화벽 친화적

```bash
# 웹 서버 실행 필요
python -m app.web --reload

# HTTP 엔드포인트 사용
curl -X POST http://localhost:8000/mcp/sse \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### 스토리지 모드 선택

#### Direct 모드 (기본값, 권장)
```json
{
  "env": {
    "MEM_MESH_STORAGE_MODE": "direct"
  }
}
```
- MCP 서버가 SQLite에 직접 접근
- 더 빠른 성능
- 단일 프로세스로 동작

#### API 모드
```json
{
  "env": {
    "MEM_MESH_STORAGE_MODE": "api",
    "MEM_MESH_API_BASE_URL": "http://localhost:8000"
  }
}
```
- MCP 서버가 FastAPI를 통해 데이터에 접근
- FastAPI 대시보드와 함께 사용 시 유용
- 별도로 `python -m app.dashboard` 실행 필요

### 독립 실행 vs MCP 연동

**독립 실행 (웹 서버)**:
- REST API로 직접 접근
- 웹 브라우저에서 API 문서 확인 가능
- curl, Postman 등으로 테스트 가능
- SSE MCP 엔드포인트 제공

**MCP 연동**:
- AI 도구 내에서 직접 사용
- 자연어로 메모리 관리 가능
- 개발 워크플로우에 완전 통합

## 환경 변수

모든 환경 변수는 `MCP_` 접두사를 사용합니다 (MCP 프로토콜 표준).

### 🆕 로깅 시스템 설정

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `MCP_LOG_LEVEL` | `INFO` | 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `MCP_LOG_FILE` | `` | 로그 파일 경로 (설정 시 파일 로깅 활성화) |
| `MCP_LOG_FORMAT` | `text` | 로그 형식 (text, json) |
| `MCP_LOG_OUTPUT` | `console` | 로그 출력 대상 (console, file, both) |

### 🌐 웹 서버 및 SSE MCP 설정

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `MEM_MESH_SERVER_HOST` | `127.0.0.1` | 웹 서버 호스트 |
| `MEM_MESH_SERVER_PORT` | `8000` | 웹 서버 포트 |
| `MEM_MESH_SERVER_WORKERS` | `1` | uvicorn worker 프로세스 수 (1-32) |

### 기존 설정 변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `MEM_MESH_STORAGE_MODE` | `direct` | 스토리지 모드 (direct, api) |
| `MEM_MESH_API_BASE_URL` | `http://localhost:8000` | API 모드에서 FastAPI 서버 URL |
| `MEM_MESH_DATABASE_PATH` | `./data/memories.db` | SQLite 데이터베이스 파일 경로 |
| `MEM_MESH_MIN_CONTENT_LENGTH` | `10` | 메모리 내용 최소 길이 |
| `MEM_MESH_MAX_CONTENT_LENGTH` | `10000` | 메모리 내용 최대 길이 |
| `MEM_MESH_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | 임베딩 모델명 |
| `MEM_MESH_EMBEDDING_DIM` | `384` | 임베딩 벡터 차원 |
| `MEM_MESH_SEARCH_THRESHOLD` | `0.5` | 검색 유사도 임계값 |
| `MEM_MESH_BUSY_TIMEOUT` | `5000` | SQLite busy timeout (밀리초) |
| `MEM_MESH_IGNORE_SSL` | `0` | SSL 인증서 검증 우회 (1=비활성화, 0=활성화) |

### 설정 예시

**.env 파일 예시**:
```bash
# 로깅 설정
MCP_LOG_LEVEL=DEBUG
MCP_LOG_FILE=./logs/mem-mesh.log
MCP_LOG_FORMAT=text

# 웹 서버 설정
MEM_MESH_SERVER_HOST=0.0.0.0
MEM_MESH_SERVER_PORT=8000

# 데이터베이스 경로
MEM_MESH_DATABASE_PATH=./data/memories.db

# 스토리지 모드 설정
MEM_MESH_STORAGE_MODE=direct

# SQLite 설정
MEM_MESH_BUSY_TIMEOUT=10000
```

**개발 환경 설정**:
```bash
# 개발용 상세 로깅 (콘솔과 파일 둘 다)
export MCP_LOG_LEVEL="DEBUG"
export MCP_LOG_FILE="./logs/dev-mem-mesh.log"
export MCP_LOG_FORMAT="text"
export MCP_LOG_OUTPUT="both"

# 웹 서버 + SSE MCP 실행
python -m app.web --reload
```

**프로덕션 환경 설정**:
```bash
# 프로덕션용 로깅 (파일만)
export MCP_LOG_LEVEL="INFO"
export MCP_LOG_FILE="/var/log/mem-mesh/mem-mesh.log"
export MCP_LOG_FORMAT="json"
export MCP_LOG_OUTPUT="file"

# 멀티 워커 설정
export MEM_MESH_SERVER_WORKERS="4"

# 프로덕션 서버 실행
python -m app.web --host 0.0.0.0 --port 8000 --workers 4
# 또는 환경변수 사용
uvicorn app.web.app:app --host 0.0.0.0 --port 8000 --workers 4
```

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

# 속성 기반 테스트 실행
pytest tests/test_properties.py

# 커버리지 포함
pytest --cov=src --cov=app
```

### 코드 품질

```bash
# 린팅
flake8 src tests app

# 타입 체크
mypy src app

# 포맷팅
black src tests app
```

## 🏗️ 아키텍처

### 새로운 통합 아키텍처 (app/)
```
app/
├── web/                   # 웹 서버 + SSE MCP (통합)
│   ├── __main__.py        # 웹 서버 진입점
│   ├── app.py             # FastAPI 앱 생성
│   ├── lifespan.py        # 애플리케이션 생명주기
│   ├── dashboard/         # 웹 대시보드 라우트
│   ├── mcp/               # SSE MCP 엔드포인트
│   └── common/            # 공통 유틸리티
├── mcp_stdio/             # FastMCP 기반 Stdio MCP
│   ├── __main__.py        # MCP 서버 진입점
│   └── server.py          # FastMCP 서버 구현
├── mcp_stdio_pure/        # 순수 MCP 프로토콜 구현
│   ├── __main__.py        # 순수 MCP 진입점
│   └── server.py          # 순수 MCP 서버
├── mcp_common/            # MCP 공통 모듈
│   ├── tools.py           # MCP 도구 핸들러
│   ├── schemas.py         # 도구 스키마 정의
│   └── storage.py         # 스토리지 관리자
└── core/                  # 핵심 비즈니스 로직
    ├── config.py          # 통합 설정 관리
    ├── version.py         # 버전 정보 중앙 관리
    ├── utils/
    │   └── logger.py      # 중앙 집중식 로깅
    ├── database/          # 데이터베이스 레이어
    ├── embeddings/        # 임베딩 서비스
    ├── services/          # 비즈니스 로직
    ├── schemas/           # Pydantic 스키마
    └── storage/           # 스토리지 추상화
        ├── base.py        # 추상 인터페이스
        ├── direct.py      # Direct SQLite 구현
        └── api.py         # API 클라이언트 구현
```

### 기존 아키텍처 (src/)
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

### 주요 개선사항

1. **통합 웹 서버**: 웹 대시보드 + SSE MCP를 하나의 서버에서 제공
2. **중앙 집중식 로깅**: 모든 모듈에서 일관된 로깅 시스템 사용
3. **MCP 구현 다양화**: FastMCP 기반과 순수 MCP 구현 제공
4. **스토리지 추상화**: Direct/API 모드 지원
5. **모듈 분리**: 각 MCP 구현이 독립적으로 실행 가능
6. **동시성 지원**: SQLite WAL 모드 활용
7. **설정 통합**: 환경변수 기반 통합 설정
8. **버전 관리**: 중앙 집중식 버전 정보 관리

## 기술 스택

- **Backend**: Python 3.9+, FastAPI
- **Database**: SQLite + sqlite-vec (벡터 검색), WAL 모드
- **Embeddings**: sentence-transformers
- **Protocol**: Model Context Protocol (MCP) 2024-11-05
- **MCP Transport**: Stdio (FastMCP, 순수 구현), SSE (Server-Sent Events)
- **Logging**: 중앙 집중식 구조화 로깅 (text/json 형식)
- **Testing**: pytest, httpx, hypothesis (속성 기반 테스트)
- **Architecture**: 통합 웹 서버 + 다중 MCP 구현

## 라이선스

MIT License

## 기여

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📋 MCP 프롬프트 가이드

mem-mesh를 다양한 AI 도구와 효과적으로 통합하기 위한 상세한 가이드를 제공합니다:

### 🎯 Cursor Rules용 프롬프트
Cursor IDE에서 mem-mesh를 활용하기 위한 완전한 설정 및 사용 가이드입니다.
- **파일**: [docs/cursor-rules-mcp-prompt.md](docs/cursor-rules-mcp-prompt.md)
- **내용**: Cursor MCP 설정, 사용 예시, 워크플로우 패턴, 문제 해결

### 🤖 AI Agents용 프롬프트  
AI 에이전트 시스템에서 mem-mesh를 통합하기 위한 기술적 가이드입니다.
- **파일**: [docs/agents-mcp-prompt.md](docs/agents-mcp-prompt.md)
- **내용**: MCP 도구 상세 설명, 에이전트 워크플로우 패턴, 고급 활용법

### 💡 주요 활용 시나리오

#### 개발팀 지식 관리
```
"JWT 인증 구현 결정사항을 메모리에 저장해줘. 보안성과 확장성을 고려한 선택이다."
"이전에 저장한 인증 관련 결정사항들을 찾아줘"
```

#### 버그 추적 및 해결
```
"로그인 페이지 특수문자 비밀번호 validation 버그를 기록해줘"
"유사한 validation 버그 해결 사례가 있나?"
```

#### 코드 스니펫 관리
```
"React Hook Form 커스텀 validation 코드를 저장해줘"
"Hook Form 관련 코드 예제들을 찾아줘"
```

#### 프로젝트 회고 및 학습
```
"user-dashboard 프로젝트의 모든 결정사항들을 정리해서 보여줘"
"이번 스프린트에서 배운 교훈들을 저장하고 싶어"
```

이 프롬프트들을 활용하여 팀의 개발 워크플로우에 mem-mesh를 완벽하게 통합하세요.

## 지원

문제가 있거나 질문이 있으시면 GitHub Issues를 통해 문의해 주세요.