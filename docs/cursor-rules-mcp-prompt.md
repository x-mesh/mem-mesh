# Cursor Rules용 MCP 프롬프트

## mem-mesh MCP 통합 가이드

mem-mesh는 개발자를 위한 중앙 메모리 서버로, Model Context Protocol(MCP)을 통해 AI 도구와 완벽하게 통합됩니다.

### 🚀 빠른 설정

#### 1. mem-mesh 설치 및 실행
```bash
# 프로젝트 클론 및 설치
git clone https://github.com/JINWOO-J/mem-mesh
cd mem-mesh
pip install -e .

# MCP 서버 실행 (Direct 모드)
python -m app.mcp
```

#### 2. Cursor MCP 설정

`.cursor/mcp.json` 파일을 생성하고 다음 내용을 추가하세요:

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/절대/경로/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "direct"
      }
    }
  }
}
```

### 🎯 사용 방법

#### 메모리 저장하기
```
"이 결정사항을 메모리에 저장해줘: JWT 토큰 방식으로 인증 구현하기로 결정했다. 보안성과 확장성을 고려한 선택이다."

"버그를 발견했어. 메모리에 기록해줘: 로그인 페이지에서 특수문자 비밀번호 입력 시 validation 에러 발생. 프로젝트는 user-portal."

"코드 스니펫을 저장하고 싶어: React Hook Form 커스텀 validation 함수 구현 코드"
```

#### 메모리 검색하기
```
"JWT 관련 이전 결정사항들을 찾아줘"

"user-portal 프로젝트의 버그 관련 메모리들을 보여줘"

"React Hook Form 사용법에 대한 코드나 메모가 있나?"

"인증 관련 아키텍처 결정사항들을 검색해줘"
```

#### 맥락 조회하기
```
"이 메모리와 관련된 다른 내용들도 보여줘: [memory-id]"

"방금 찾은 JWT 결정사항과 연관된 메모리들을 더 찾아줘"
```

#### 프로젝트 관리
```
"현재 프로젝트의 메모리 통계를 알려줘"

"user-portal 프로젝트의 모든 결정사항들을 정리해서 보여줘"

"이번 주에 저장한 메모리들의 카테고리별 분포를 알려줘"
```

### 🔧 고급 설정

#### API 모드 사용 (웹 UI와 함께)
```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/절대/경로/to/mem-mesh",
      "env": {
        "MEM_MESH_STORAGE_MODE": "api",
        "MEM_MESH_API_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

API 모드 사용 시 별도로 FastAPI 대시보드를 실행해야 합니다:
```bash
python -m app.dashboard
```

#### 환경 변수 커스터마이징
```json
{
  "env": {
    "MEM_MESH_DATABASE_PATH": "./custom/path/memories.db",
    "MEM_MESH_LOG_LEVEL": "DEBUG",
    "MEM_MESH_EMBEDDING_MODEL": "all-mpnet-base-v2"
  }
}
```

### 💡 효과적인 사용 팁

#### 1. 구체적인 컨텍스트 제공
```
❌ "이거 저장해줘: 버그 있음"
✅ "로그인 API에서 버그 발견: 동시 로그인 시 세션 충돌 발생. auth-service 프로젝트에 저장해줘."
```

#### 2. 프로젝트 ID 활용
```
✅ "user-portal 프로젝트의 인증 관련 이슈들을 모두 찾아줘"
✅ "e-commerce 프로젝트에 결정사항 저장: 결제 시스템으로 Stripe 채택"
```

#### 3. 카테고리 명시
```
✅ "이 아이디어를 저장해줘: 사용자 경험 개선을 위한 다크모드 지원"
✅ "버그 리포트: 검색 기능에서 특수문자 처리 오류"
✅ "결정사항 기록: 코드 리뷰 프로세스에 자동화 도구 도입"
```

#### 4. 태그 활용
```
✅ "성능 최적화 아이디어를 저장해줘. 태그는 performance, optimization, database로 설정"
```

### 🚀 실제 워크플로우 예제

#### 새 기능 개발 시작
```
"새 기능 개발을 시작해. 메모리에 저장해줘: 사용자 프로필 편집 기능 개발 시작. React Hook Form과 Yup validation을 사용하기로 결정. 프로젝트는 user-dashboard."
```

#### 개발 중 이슈 발견
```
"버그를 발견했어: 프로필 이미지 업로드 시 파일 크기 제한이 제대로 작동하지 않는다. user-dashboard 프로젝트에 기록해줘."
```

#### 해결책 아이디어 저장
```
"아이디어 저장: 이미지 업로드 전에 클라이언트 사이드에서 파일 크기를 체크하고, 서버에서도 이중 검증하는 방식으로 개선하자."
```

#### 관련 내용 검색
```
"프로필 편집이나 이미지 업로드와 관련된 모든 메모리를 찾아줘"
```

#### 프로젝트 회고
```
"user-dashboard 프로젝트의 모든 결정사항들을 정리해서 보여줘"
```

### 🔍 사용 가능한 MCP 도구들

1. **mem-mesh.add**: 새 메모리 추가
2. **mem-mesh.search**: 벡터 검색으로 메모리 찾기
3. **mem-mesh.context**: 특정 메모리의 관련 맥락 조회
4. **mem-mesh.update**: 기존 메모리 수정
5. **mem-mesh.delete**: 메모리 삭제
6. **mem-mesh.stats**: 메모리 통계 조회

### 🛠️ 문제 해결

#### 연결 문제
- `cwd` 경로가 절대 경로인지 확인
- Python 환경에 mem-mesh가 설치되었는지 확인
- MCP 서버가 실행 중인지 확인

#### 성능 최적화
- Direct 모드 사용 (기본값)
- 적절한 임베딩 모델 선택
- 데이터베이스 경로를 SSD에 설정

#### 로그 확인
```bash
# 디버그 모드로 실행
MEM_MESH_LOG_LEVEL=DEBUG python -m app.mcp
```

### 📚 추가 리소스

- [전체 README](../README.md)
- [API 문서](http://localhost:8000/docs) (FastAPI 서버 실행 시)
- [웹 UI](http://localhost:8000) (FastAPI 서버 실행 시)
- [임베딩 모델 테스트 가이드](embedding_model_testing_guide.md)

---

이 프롬프트를 `.cursor-rules` 파일이나 프로젝트 문서에 포함하여 팀원들이 mem-mesh를 효과적으로 활용할 수 있도록 도와주세요.