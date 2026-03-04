# mem-mesh 환경 설정 가이드

## Python 환경 설정

### 1. pyenv로 Python 3.11 사용
```bash
# Python 3.11.9가 이미 설치되어 있음
pyenv local 3.11.9
```

### 2. 가상환경 생성 및 활성화
```bash
# 가상환경 생성 (이미 생성됨)
python -m venv .venv

# 가상환경 활성화
source .venv/bin/activate
```

### 3. 패키지 설치
```bash
# pip 업그레이드
pip install --upgrade pip

# requirements.txt로 전체 패키지 설치
pip install -r requirements.txt
```

## 설치된 주요 패키지

- **Python**: 3.11.9
- **torch**: 2.2.2
- **sentence-transformers**: 3.4.1
- **transformers**: 4.57.6
- **FastAPI**: 0.115.14
- **uvicorn**: 0.31.1
- **mcp**: 1.26.0
- **fastmcp**: 0.4.1
- **sqlite-vec**: 0.1.7a2
- **numpy**: 1.26.4

## 동작 확인

```bash
# 가상환경 활성화 후
source .venv/bin/activate

# torch 확인
python -c "import torch; print(f'✓ torch {torch.__version__} OK')"

# sentence-transformers 확인
python -c "from sentence_transformers import SentenceTransformer; print('✓ sentence-transformers import OK')"

# FastAPI 앱 확인
python -c "from app.web.app import app; print('✓ FastAPI import OK')"

# 임베딩 모델 로드 테스트
python -c "from sentence_transformers import SentenceTransformer; model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); print(f'✓ Model loaded: dimension={model.get_sentence_embedding_dimension()}')"
```

## 개발 서버 실행

```bash
# 가상환경 활성화
source .venv/bin/activate

# FastAPI + SSE MCP dashboard
python -m app.web --reload

# FastMCP 기반 stdio MCP 서버
python -m app.mcp_stdio

# Pure MCP stdio MCP 서버
python -m app.mcp_stdio_pure
```

## 주의사항

- Python 3.13에서는 torch가 설치되지 않으므로 **반드시 Python 3.11**을 사용해야 합니다.
- 가상환경을 활성화한 상태에서 모든 명령을 실행하세요.
- sentence-transformers는 torch를 의존성으로 자동 설치합니다.
