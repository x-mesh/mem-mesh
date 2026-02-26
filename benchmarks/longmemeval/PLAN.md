# LongMemEval 벤치마크 실행 계획

## 완료된 작업

### 구현 (완료)
- [x] 벤치마크 모듈 13개 파일 구현 (`benchmarks/longmemeval/`)
- [x] 단위/통합 테스트 97개 통과 (`tests/benchmarks/`)
- [x] pysqlite3 설치 → sqlite-vec hybrid search 활성화 확인
- [x] Mock 데이터 20개 질문으로 검색 품질 검증 (정보 검색 17/17 = 100% recall)

### 파일 구조
```
benchmarks/longmemeval/
├── models.py, config.py, config.yaml   # 데이터 모델 + 설정
├── dataset.py                          # HuggingFace 로더
├── indexer.py                          # Session/Window/Turn 인덱싱
├── retriever.py                        # 검색 + recall/NDCG 메트릭
├── generator.py                        # litellm LLM 답변 생성
├── evaluator.py                        # GPT-4o judge
├── translator.py                       # 한국어 번역 파이프라인
├── reporter.py                         # 리포트 (Console/Markdown/JSON)
├── adapter.py                          # 오케스트레이터
├── __main__.py                         # CLI
└── run_retrieval_bench.py              # 검색-only 벤치마크 (LLM 불필요)
```

---

## 남은 작업

### Phase 1: 실제 데이터셋으로 검색 품질 측정 (LLM 불필요)

```bash
# 1. 의존성 설치
pip install datasets tqdm

# 2. run_retrieval_bench.py를 실제 데이터셋으로 확장하거나,
#    adapter에서 생성/평가 단계를 건너뛰는 retrieval-only 모드 추가
#    → 500개 질문의 recall@k, NDCG@k 측정

# 3. 인덱싱 전략 비교 (session vs window vs turn)
python -m benchmarks.longmemeval run --config config.yaml  # retrieval-only 모드 필요
```

**목표**: 500개 질문에서 recall_any@10, recall_all@10, NDCG@10 확보

### Phase 2: 전체 파이프라인 (LLM 필요)

```bash
# 1. API 키 설정
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...

# 2. 추가 의존성
pip install litellm

# 3. 영문 벤치마크 실행 (500개 질문, ~$5-10 비용)
python -m benchmarks.longmemeval run --config benchmarks/longmemeval/config.yaml

# 4. 결과 확인
python -m benchmarks.longmemeval report --results benchmarks/longmemeval/results/en_session.jsonl
```

**config.yaml 조정 포인트**:
- `generation.model`: claude-sonnet-4-20250514 (기본) 또는 gpt-4o
- `evaluation.judge_model`: gpt-4o (기본)
- `retrieval.top_k`: 10 (기본, 최대 20)
- `indexing.strategy`: session (기본) → window, turn 비교

### Phase 3: 한국어 벤치마크

```bash
# 1. 번역 (Phase 1: QA만, ~$1)
python -m benchmarks.longmemeval translate --phase 1

# 2. 번역 (Phase 2: 증거 세션 추가, ~$5)
python -m benchmarks.longmemeval translate --phase 2

# 3. 한국어 벤치마크 실행
#    config.yaml에서 dataset.language를 "ko"로 변경
python -m benchmarks.longmemeval run --config benchmarks/longmemeval/config.yaml
```

### Phase 4: 결과 비교 및 리포트

최종 비교표 생성:
```
| System       | Overall | Info Extract | Multi-Session | Temporal | Knowledge | Abstention |
|-------------|---------|-------------|---------------|----------|-----------|------------|
| mem-mesh EN | ?%      | ?%          | ?%            | ?%       | ?%        | ?%         |
| mem-mesh KO | ?%      | ?%          | ?%            | ?%       | ?%        | ?%         |
| OMEGA       | 95.4%   | -           | -             | -        | -         | -          |
| GPT-4o RAG  | 72%     | -           | -             | -        | -         | -          |
```

---

## 주의사항

- **체크포인트**: 50개마다 자동 저장. 중단 후 재실행하면 이어서 진행
- **비용**: 영문 전체 ~$5-10 (Claude 생성 + GPT-4o 평가)
- **시간**: 500개 질문 × (인덱싱 + 검색 + 생성 + 평가) ≈ 30-60분
- **DB 격리**: 벤치마크 전용 DB (`data/benchmark_lme.db`), 프로덕션 DB 영향 없음
- **sqlite-vec**: pysqlite3 설치 필수 (`pip install pysqlite3`)
- **SearchParams limit**: 최대 20 (코드에서 이미 제한)

## 빠른 시작 (다음 세션)

```bash
cd /Users/jinwoo/work/project/mem-mesh

# 테스트 확인
python -m pytest tests/benchmarks/ -v

# Mock 벤치마크 재실행
python benchmarks/longmemeval/run_retrieval_bench.py

# 실제 데이터셋 벤치마크 (Phase 1부터)
pip install datasets tqdm
# → Phase 1 진행
```
