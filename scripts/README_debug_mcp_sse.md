# MCP/SSE 디버깅 스크립트 사용법

## 개요

`debug_mcp_sse_search.py`는 MCP/SSE 프로토콜을 통해 mem-mesh 서버와 직접 통신하여 메모리를 조회/추가하는 디버깅 도구입니다.

## 사전 요구사항

1. mem-mesh 서버가 실행 중이어야 합니다:
   ```bash
   python -m app.web --reload
   ```

2. httpx 패키지가 설치되어 있어야 합니다 (requirements.txt에 포함됨)

## 사용 예시

### 1. 메모리 검색 (search)

#### 버그 카테고리 검색
```bash
python scripts/debug_mcp_sse_search.py search --category bug --limit 10
```

#### 특정 쿼리로 검색
```bash
python scripts/debug_mcp_sse_search.py search --query "검색 성능 문제" --limit 20
```

#### 프로젝트별 검색
```bash
python scripts/debug_mcp_sse_search.py search --project mem-mesh --category task
```

### 2. 메모리 추가 (add)

#### 기본 메모리 추가
```bash
python scripts/debug_mcp_sse_search.py add \
  --content "MCP/SSE 디버깅 스크립트 작성 완료" \
  --category task \
  --project mem-mesh \
  --tags "mcp,sse,debugging"
```

#### 버그 리포트 추가
```bash
python scripts/debug_mcp_sse_search.py add \
  --content "검색 결과가 비어있는 문제 발견. limit 파라미터 검증 필요" \
  --category bug \
  --project mem-mesh \
  --tags "search,bug,validation"
```

#### 아이디어 추가
```bash
python scripts/debug_mcp_sse_search.py add \
  --content "배치 검색 API 추가하여 여러 쿼리를 한번에 처리" \
  --category idea \
  --tags "api,performance,batch"
```

### 3. 통계 조회 (stats)

#### 전체 통계
```bash
python scripts/debug_mcp_sse_search.py stats
```

#### 프로젝트별 통계
```bash
python scripts/debug_mcp_sse_search.py stats --project mem-mesh
```

### 4. 다른 서버 URL 사용
```bash
python scripts/debug_mcp_sse_search.py search --url http://localhost:9000 --category bug
```

## 명령어 구조

```bash
python scripts/debug_mcp_sse_search.py <command> [options]
```

### Commands

- `search` - 메모리 검색 (기본 명령어)
- `add` - 메모리 추가
- `stats` - 통계 조회

### Search 옵션

- `--query`: 검색 쿼리 (기본: "bug error issue")
- `--category`: 카테고리 필터 (task, bug, idea, decision, incident, code_snippet, git-history)
- `--project`: 프로젝트 ID 필터
- `--limit`: 결과 개수 제한 (기본: 10, 최대: 20)

### Add 옵션

- `--content`: 메모리 내용 (필수, **최소 10자 이상**)
- `--category`: 카테고리 (기본: task)
- `--project`: 프로젝트 ID
- `--tags`: 태그 (쉼표로 구분)

### Stats 옵션

- `--project`: 프로젝트 ID 필터

### 공통 옵션

- `--url`: 서버 URL (기본: http://localhost:8000)

## 출력 형식

### Search 출력
```
📤 Request to http://localhost:8000/mcp/sse
Tool: search
Arguments: {
  "query": "bug error issue",
  "limit": 10,
  "response_format": "standard",
  "category": "bug"
}
--------------------------------------------------------------------------------
📥 Response Status: 200

✅ Search Results:
================================================================================

Found 5 results:
--------------------------------------------------------------------------------

1. Memory ID: abc123
   Category: bug
   Project: mem-mesh
   Score: 0.8542
   Created: 2026-01-22T03:15:00+00:00
   Content: 검색 성능 저하 문제 발견. 벡터 검색 시 응답 시간이 2초 이상 소요됨...
   Tags: performance, search, bug
```

### Add 출력
```
📤 Request to http://localhost:8000/mcp/sse
Tool: add
Arguments: {
  "content": "MCP/SSE 디버깅 스크립트 작성 완료",
  "category": "task",
  "project_id": "mem-mesh",
  "tags": ["mcp", "sse", "debugging"]
}
--------------------------------------------------------------------------------
📥 Response Status: 200

✅ Memory Added:
================================================================================
Memory ID: xyz789
Category: task
Project: mem-mesh
Tags: mcp, sse, debugging
Created: 2026-01-22T04:25:00+00:00
```

## 디버깅 팁

1. **연결 실패 시**: 서버가 실행 중인지 확인
2. **빈 결과**: 쿼리를 더 일반적으로 변경하거나 limit 증가
3. **오류 메시지**: JSON 응답에서 상세 오류 정보 확인
4. **메모리 추가 실패**: 
   - content 길이 제약: **최소 10자, 최대 10000자**
   - 예시: "작업 내용" (5자) ❌ → "MCP 디버깅 스크립트 작성" (15자) ✅

## 워크플로우 예시

```bash
# 1. 현재 버그 확인
python scripts/debug_mcp_sse_search.py search --category bug --project mem-mesh

# 2. 새로운 버그 추가
python scripts/debug_mcp_sse_search.py add \
  --content "SSE 응답 파싱 시 빈 라인 처리 오류" \
  --category bug \
  --project mem-mesh \
  --tags "sse,parsing,bug"

# 3. 추가된 버그 검색으로 확인
python scripts/debug_mcp_sse_search.py search --query "SSE 응답 파싱" --limit 5

# 4. 프로젝트 통계 확인
python scripts/debug_mcp_sse_search.py stats --project mem-mesh
```
