# mem-mesh 전략 계획서

> 작성일: 2026-02-22 (updated)
> 버전: 1.0.4 기준
> 상태: Draft v2

---

## 목차

- [1. Executive Summary](#1-executive-summary)
- [2. 현재 상태 분석](#2-현재-상태-분석)
- [3. 경쟁 환경](#3-경쟁-환경)
- [4. 기존 개선 제안 평가](#4-기존-개선-제안-평가)
- [5. 전략적 방향성](#5-전략적-방향성)
- [6. AI 도구별 통합 전략](#6-ai-도구별-통합-전략)
- [7. 제품 개선 계획](#7-제품-개선-계획)
- [8. 수익 모델](#8-수익-모델)
- [9. 사용자 확보 및 성장](#9-사용자-확보-및-성장)
- [10. 실행 로드맵](#10-실행-로드맵)
- [11. OMEGA Memory 경쟁 전략](#11-omega-memory-경쟁-전략)
- [12. LongMemEval 벤치마킹 계획](#12-longmemeval-벤치마킹-계획)

---

## 1. Executive Summary

### mem-mesh란

AI 코딩 도구(Cursor, Claude Code, Kiro, Antigravity, Windsurf)가 MCP(Model Context Protocol)를 통해 작업 중 생성되는 지식을 중앙에서 저장·검색·관리하는 영속 메모리 시스템.

### 핵심 강점

- 15개 MCP 도구, 하이브리드 검색(RRF), 세션/핀 워크플로우
- 한국어 최적화 (경쟁자 중 유일)
- 로컬 SQLite 기반, 오프라인 동작, 외부 의존성 없음
- 토큰 효율성 (batch 30-50% 절감, session compress 90% 절감)

### 핵심 과제

- 경쟁자 20개+ 존재 (진입 장벽 낮음)
- 발견성 부족 (레지스트리 미등록)
- 설치 마찰 (Python + pip + 모델 다운로드)
- 15개 도구 = 학습 부담
- "왜 써야 하는지" 가치 증명 부족

### 전략 요약

```
현재 포지셔닝:  "MCP 메모리 서버" (경쟁자 20개+)
목표 포지셔닝:  "모든 AI 도구를 연결하는 크로스 툴 기억 허브" (카테고리 1등)
```

---

## 2. 현재 상태 분석

### 2.1 아키텍처 개요

```
┌─────────────────────────────────────────────┐
│  Clients                                     │
│  Cursor · Claude Code · Kiro · Web           │
└───────────┬─────────────────┬───────────────┘
            │                 │
      ┌─────┴─────┐   ┌──────┴──────┐
      │ Stdio MCP │   │  SSE MCP    │
      └─────┬─────┘   └──────┬──────┘
            └────────┬────────┘
              ┌──────┴──────┐
              │  mcp_common │
              │  (도구/디스패처) │
              └──────┬──────┘
              ┌──────┴──────┐
              │   Storage   │
              └──────┬──────┘
         ┌───────────┼───────────┐
    ┌────┴────┐ ┌────┴────┐ ┌───┴────┐
    │ SQLite  │ │sqlite-vec│ │ FTS5   │
    │(메타데이터)│ │(벡터 검색)│ │(전문검색)│
    └─────────┘ └─────────┘ └────────┘
```

### 2.2 기술 스택

| 계층 | 기술 | 비고 |
|------|------|------|
| 런타임 | Python 3.9+ | PyPI 배포 |
| 웹 프레임워크 | FastAPI + Uvicorn | Dashboard + SSE MCP |
| MCP | mcp + fastmcp | Stdio + SSE 듀얼 트랜스포트 |
| DB | SQLite + sqlite-vec + FTS5 | 단일 파일, 외부 의존성 없음 |
| 임베딩 | sentence-transformers | 기본 all-MiniLM-L6-v2 (384차원) |
| 검색 | 하이브리드 RRF | 벡터 + FTS5 Reciprocal Rank Fusion |

### 2.3 MCP 도구 (15개)

| 카테고리 | 도구 | 설명 |
|---------|------|------|
| **Core CRUD** | add, search, context, update, delete | 메모리 기본 연산 |
| **세션/핀** | session_resume, session_end, pin_add, pin_complete, pin_promote | 작업 흐름 관리 |
| **관계** | link, unlink, get_links | 메모리 그래프 |
| **유틸** | stats, batch_operations | 통계, 토큰 절감 |

### 2.4 데이터 모델

**Memory 모델:**

```python
class Memory:
    id: str              # UUID
    content: str         # 10~10,000자
    content_hash: str    # SHA256 (중복 방지)
    project_id: str      # 프로젝트 필터
    category: str        # task|bug|idea|decision|incident|code_snippet|git-history
    source: str          # 출처
    embedding: bytes     # float32 벡터 (BLOB)
    tags: str            # JSON 배열
    created_at: str      # ISO8601
    updated_at: str      # ISO8601
```

**관계 모델:**

```python
class MemoryRelation:
    source_id: str       # FK → memories
    target_id: str       # FK → memories
    relation_type: str   # related|parent|child|supersedes|references|depends_on|similar
    strength: float      # 0.0~1.0
    metadata: str        # JSON
```

**세션/핀 모델:**

```
Session → Pin (1:N)
Pin → Memory (promoted_to_memory_id, 승격 시)
```

### 2.5 검색 파이프라인

```
Query → 의도 분석 → 쿼리 확장 (한영 번역) → 캐시 확인
  → [벡터 검색] + [FTS5 검색] (병렬)
  → RRF 결합 (k=60, text_weight=1.2, vector_weight=1.0)
  → 품질 스코어링 → 노이즈 필터 → 프로젝트명 부스트
  → 점수 정규화 (sigmoid) → 결과 반환
```

### 2.6 현재의 강점과 약점

**강점:**

| 항목 | 설명 |
|------|------|
| 기능 완성도 | 15개 도구, 하이브리드 검색, 세션/핀, 관계, 배치 |
| 한국어 최적화 | n-gram FTS, E5 prefix, sigmoid 정규화 (유일) |
| 프라이버시 | 로컬 SQLite, 오프라인 동작, 데이터 외부 전송 없음 |
| 토큰 효율 | batch 30-50%, session compress 90% 절감 |
| 듀얼 트랜스포트 | Stdio + SSE (Streamable HTTP 2025-03-26) |

**약점:**

| 항목 | 설명 |
|------|------|
| 발견 불가 | Awesome MCP Servers, LobeHub, npm에 미등록 |
| 설치 마찰 | Python + pip + 모델 다운로드 + .env 설정 |
| 학습 부담 | 15개 도구를 한꺼번에 노출 |
| 가치 증명 부재 | 사용 효과를 숫자로 보여주지 못함 |
| 커뮤니티 부재 | GitHub stars, 사용 사례, 후기 부족 |
| Python 전용 | Node.js/Go SDK 없음 |

---

## 3. 경쟁 환경

### 3.1 MCP 메모리 서버 시장

- MCP 서버 총 13,000개+ (2025년 기준)
- 메모리 특화 서버 20개+ (경쟁 밀도 낮음)
- 진입 장벽 낮음 (SQLite + sentence-transformers로 구현 가능)
- 표준화 미비 (스키마/프로토콜 합의 없음)

### 3.2 주요 경쟁자

#### Tier 1: 직접 경쟁 (유사 기능)

| 경쟁자 | 기술 스택 | 차별점 | 위협도 |
|--------|----------|--------|--------|
| **Mem0 (OpenMemory)** | Qdrant + PostgreSQL | VC 펀딩, 벤치마크, SaaS | **높음** |
| **OMEGA Memory** | SQLite, PyPI | 25개 도구, 큰 도구 표면 | 중간 |
| **Memento** | SQLite + FTS5 + bge-m3 | 오프라인 퍼스트 | 중간 |
| **Claude Memory MCP** | SQLite + sentence-transformers | 확립된 레지스트리 존재 | 중간 |
| **MCP Memory Keeper** | npm | 크로스 세션 메모리 공유 | 낮음 |

#### Tier 2: 그래프/엔터프라이즈

| 경쟁자 | 기술 스택 | 차별점 |
|--------|----------|--------|
| Memory Graph MCP | 그래프 DB | 엔티티-관계 모델링 |
| MCP Memory Service | SQLite + FastAPI | 멀티 에이전트 지원 |
| MemoryGraph MCP | Elasticsearch | 엔터프라이즈 스케일 |

#### Tier 3: 내장 메모리 (IDE 자체 제공)

| IDE | 메모리 시스템 | mem-mesh와의 관계 |
|-----|-------------|-----------------|
| **Google Antigravity** | Knowledge Items (자동 캡처) | 직접 경쟁하되, 크로스 툴 불가 |
| Kiro | Spec/Steering 기반 | 보완적 |

### 3.3 mem-mesh vs 경쟁자 비교

| 기능 | mem-mesh | Mem0 | OMEGA | Antigravity |
|------|---------|------|-------|-------------|
| 로컬 SQLite | O | X (Qdrant) | O | 내장 |
| 오프라인 | O | X (SaaS) | O | O |
| 하이브리드 검색 (RRF) | O | O | O | 불명 |
| 한국어 최적화 | **O (유일)** | X | X | X |
| 배치 연산 (토큰 절감) | O | O | X | X |
| 세션/핀 워크플로우 | **O (유일)** | X | X | X |
| 메모리 관계 (7타입) | O | O | O | X |
| 웹 대시보드 | O | O | X | 내장 |
| 크로스 툴 메모리 | **O** | O | O | **X (단일 IDE)** |
| 내장 자동 캡처 | X | X | X | **O** |
| 엔터프라이즈 (RBAC) | X | O | X | X |

### 3.4 경쟁 우위 요약

1. **한국어 시장 독점** — 한국어 최적화 메모리 서버 유일
2. **크로스 툴 허브** — Antigravity Knowledge Items와 달리 모든 도구 연결
3. **세션/핀 워크플로우** — 경쟁자에 없는 작업 흐름 관리
4. **토큰 효율** — 명시적 토큰 예산 관리 (batch, session compress)
5. **프라이버시** — Mem0(SaaS) 대비 완전 로컬

---

## 4. 기존 개선 제안 평가

사용자가 제안한 3가지 개선안에 대한 기술적 평가.

### 4.1 계층적 메모리 (Hierarchical Memory / TreeRAG)

**제안 내용:**

- Memory 모델에 `parent_id`/`group_id` 추가
- 프로젝트(Root) → 세션/토픽(Node) → 개별 Task(Leaf) 구조
- 세션 종료 시 자동 요약 → 상위 레벨 메모리 생성
- Tree Traversal 기반 검색 (상위 먼저, 필요 시 하위로)

**평가:**

| 항목 | 분석 |
|------|------|
| **기존 기능 중복** | `memory_relations` 테이블에 `parent`/`child` 관계 타입 이미 존재. `parent_id` 추가는 비정규화(denormalization) |
| **자동 요약 불가** | mem-mesh는 MCP 도구 서버 — LLM이 내장되어 있지 않음. 요약 생성은 아키텍처상 불가능 |
| **스케일 불일치** | 메모리 수백~수천 건 규모에서 Tree Traversal이 벡터 검색 대비 이점 없음 |
| **세션/핀 중복** | `sessions → pins → promoted_to_memory` 흐름이 이미 2단계 계층 제공 |

**결론: 효용 낮음** — 핵심 기능(자동 요약)이 아키텍처상 불가능하고, 나머지는 기존 기능과 중복

### 4.2 Small-to-Large Retrieval (검색과 추출의 분리)

**제안 내용:**

- 긴 문서를 검색용 '작은 청크'와 원본 '전체 문서'로 분리 저장
- 작은 청크로 검색 (정밀도 향상)
- LLM에 전달 시 전체 문서/앞뒤 문맥(Window) 로드

**평가:**

| 항목 | 분석 |
|------|------|
| **콘텐츠 크기** | 메모리 최대 10,000자 (~2,500토큰) — 이미 "청크" 크기. 더 쪼갤 이유 없음 |
| **문제 부재** | Small-to-Large는 논문 50페이지를 검색할 때 의미 있음. 메모리 시스템에서는 해결할 문제가 없음 |
| **복잡성 증가** | 별도 `chunks` 테이블, 부모-자식 매핑, 2단계 검색 — DB 복잡성만 증가 |

**결론: 효용 매우 낮음** — RAG 시스템 패턴을 메모리 시스템에 무리하게 적용한 사례. 해결하려는 문제(문맥 잘림)가 현재 스케일에서 발생하지 않음

### 4.3 Agentic Context Engineering (ACE & Evolving Playbook)

**제안 내용:**

- `learning`/`playbook` 카테고리 추가
- 작업 완료 후 에이전트가 성공/실패 분석 → learning으로 저장
- auto_context에서 과거 교훈을 시스템 프롬프트에 자동 주입

**평가:**

| 하위 항목 | 가능 여부 | 분석 |
|----------|---------|------|
| 카테고리 추가 | **O (쉬움)** | enum에 `learning`/`playbook` 추가하면 끝. 유용함 |
| 자동 반성 | **X (범위 밖)** | Claude(호출자)가 반성하고 `add` 도구로 저장해야 함. mem-mesh 코드 변경 아님 |
| 시스템 프롬프트 주입 | **X (불가)** | MCP 프로토콜은 request-response. 서버가 시스템 프롬프트를 강제 주입할 수 없음 |
| session_resume에 learning 포함 | **O (유용)** | resume 응답에 해당 프로젝트의 learning 메모리를 함께 반환 |

**결론: 부분적 효용** — 카테고리 추가와 session_resume 강화는 가치 있음. 자동 반성과 프롬프트 주입은 아키텍처상 mem-mesh의 역할이 아님

### 4.4 공통 교훈

세 제안 모두 **"LLM 에이전트 시스템"의 패턴을 "MCP 도구 서버"에 적용하려는 범주 오류(Category Error)**가 있음.

mem-mesh의 아키텍처적 제약:

- **LLM 미내장** — 요약, 반성, 분석 등 추론 작업 불가
- **MCP 도구 서버** — 호출받으면 응답하는 수동적 구조
- **소규모 데이터** — 수백~수천 건 규모에서 복잡한 검색 구조 불필요

---

## 5. 전략적 방향성

### 5.1 포지셔닝 전환

```
현재:  "AI 에이전트를 위한 메모리 시스템" (인프라 레이어, 대체 가능)
전환:  "모든 AI 도구를 연결하는 크로스 툴 기억 허브" (카테고리 1등)
```

**핵심 질문 전환:**

| 기존 | 전환 |
|------|------|
| "AI가 기억하게 해줄까?" | "어제 작업을 오늘 이어서 할 수 있을까?" |
| "메모리를 저장/검색하자" | "내 개발 맥락이 끊기지 않게 하자" |
| "메모리 서버" | "개발자의 제2의 뇌" |

### 5.2 차별화 전략

#### Antigravity Knowledge Items와의 차별화

Google Antigravity는 자체 영속 메모리(Knowledge Items)를 내장. 자동 캡처 기능으로 mem-mesh보다 편리함.

**하지만 결정적 약점:** Antigravity 안에서만 작동. 다른 도구로 내보내기 불가.

| | Knowledge Items | mem-mesh |
|--|----------------|----------|
| 자동 캡처 | O (AI가 알아서) | X (호출 필요) |
| **크로스 툴** | **X (Antigravity 전용)** | **O (모든 MCP 클라이언트)** |
| 내보내기/가져오기 | X | O (API, Dashboard) |
| 팀 공유 | X | 가능 (서버 기반) |
| 한국어 최적화 | X | O |

**전략:** "어떤 IDE를 쓰든 같은 기억" — 크로스 툴 허브가 킬러 밸류

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  Cursor  │   │  Claude  │   │Antigravity│  │  Kiro    │
│          │   │  Code    │   │          │   │          │
└────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │              │
     └──────────────┴──────────────┴──────────────┘
                           │
                    ┌──────┴──────┐
                    │  mem-mesh   │  ← 크로스 툴 기억 허브
                    │ (통합 기억)  │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │  Dashboard  │  ← 시각화/관리/팀 공유
                    └─────────────┘
```

#### Mem0과의 차별화

| | mem-mesh | Mem0 |
|--|---------|------|
| 배포 | 완전 로컬 (SQLite) | SaaS (Qdrant Cloud) |
| 비용 | 무료 | Freemium ($99-499/월) |
| 프라이버시 | 데이터 외부 전송 없음 | 클라우드 전송 |
| 한국어 | 최적화 | 미지원 |
| 세션/핀 | 고유 워크플로우 | 미지원 |

#### 시간 인식 검색 (Temporal-Aware Search)

검색에 시간을 1급 차원으로 도입. Zep의 Temporal Knowledge Graph 접근과 달리,
기존 SQLite 인덱스 + RRF 파이프라인 확장으로 구현하여 Zero-infrastructure 유지.

**경쟁자 비교:**

| | mem-mesh | Zep | scanadi/mcp-ai-memory |
|--|---------|-----|---------|
| 접근법 | 검색 파이프라인 통합 (filter/boost/decay) | Temporal Knowledge Graph | Memory lifecycle states |
| 복잡성 | 낮음 (기존 아키텍처 확장) | 높음 (Neo4j 필요) | 중간 (상태 머신) |
| 인프라 | SQLite only | Neo4j + 추가 DB | SQLite |
| 한국어 시간 표현 | **O** | X | X |
| MCP 네이티브 | O | X | O |

**사용 예시:**

```python
# 시간 범위 필터
search(query="DB 스키마", time_range="this_week")

# 시간 부스트 (범위 내 우선, 밖도 포함)
search(query="버그 수정", time_range="today", temporal_mode="boost")

# 감쇠 모드 (최근일수록 높은 점수)
search(query="아키텍처 결정", temporal_mode="decay")

# ISO 날짜 범위
search(query="마이그레이션", date_from="2026-02-01", date_to="2026-02-15")
```

**파라미터:**

- `time_range`: `today` | `yesterday` | `this_week` | `last_week` | `this_month` | `last_month` | `this_quarter`
- `date_from` / `date_to`: ISO8601 날짜 (YYYY-MM-DD)
- `temporal_mode`: `filter` (범위 내만) | `boost` (가중치, 기본값) | `decay` (시간 감쇠)

**핵심 차별점:** LLM이 `time_range="this_week"` 같은 단축어를 자연스럽게 생성. ISO 날짜 정확도 문제 회피.

---

## 6. AI 도구별 통합 전략

### 6.1 MCP 도구 호출의 현실

**핵심 제약:** 모든 AI 코딩 도구에서 MCP 도구 호출은 **LLM이 결정**합니다. 프로그래매틱 자동 호출은 제한적.

### 6.2 도구별 자동화 메커니즘 비교

| 메커니즘 | Claude Code | Cursor | Kiro | Antigravity | Windsurf |
|---------|------------|--------|------|-------------|----------|
| **MCP 도구 호출** | O | O | O | O | O |
| **규칙 파일** | CLAUDE.md | .cursorrules | Steering | .antigravity/rules.md | Rules |
| **Hook: 세션 시작/종료** | SessionStart/End | X | Lifecycle | X | X |
| **Hook: 도구 사용 전/후** | PreToolUse/PostToolUse | beforeShellExecution (beta) | Pre/Post Tool Use | X | X |
| **Hook: 파일 이벤트** | X | X | File saved/created/deleted | X | X |
| **Hook: Git 이벤트** | X | X | Spec task | X | X |
| **내장 메모리** | X | X | X | Knowledge Items | X |
| **자동화 방식** | Hook + LLM | LLM only | Hook + LLM | LLM only | LLM only |

### 6.3 자동화 분류

```
Hook으로 진짜 자동화 가능:  Kiro > Claude Code
LLM 지시에만 의존:          Cursor, Antigravity, Windsurf
자체 메모리 내장:           Antigravity (Knowledge Items)
```

### 6.4 자동화 신뢰도 계층

| 계층 | 방법 | 신뢰도 | 도구 범위 |
|------|------|--------|---------|
| **Git Hook / CI** | 셸 스크립트 | **100%** | 모든 도구 |
| **IDE Hook** | Kiro/Claude Code hook | **~95%** | 2/5 도구 |
| **규칙 파일 지시** | "시작 시 호출하라" | **~80%** | 모든 도구 |
| **LLM 자율 판단** | AI가 알아서 | **~50%** | 모든 도구 |
| **시스템 프롬프트 주입** | MCP에서 강제 | **불가** | — |

### 6.5 mem-mesh 자동화 전략

위에서 아래로 (높은 신뢰도 우선) 투자해야 함.

#### 계층 1: 도구 무관 자동화 (100% 신뢰, 최우선)

MCP 프로토콜 밖에서 동작. 어떤 IDE를 쓰든 Git은 공통.

```bash
# Git hook — 커밋 시 자동 메모리 저장
# .git/hooks/post-commit
#!/bin/bash
mem-mesh add \
  --category git-history \
  --content "$(git log -1 --format='%s%n%n%b')" \
  --project "$(basename $(pwd))"
```

```bash
# CI/CD 연동 — GitHub Actions에서 배포 기록
- name: Save deployment memory
  run: mem-mesh add --category decision --content "v1.2.0 deployed to prod"
```

```bash
# 파일 워처 데몬 — IDE 무관
mem-mesh watch --project my-app --paths "src/**"
```

```bash
# CLI 래퍼 — 명령어 결과를 자동 기록
mem-mesh wrap "npm test"
# → 실패 시 에러 내용 자동 저장
# → 성공 시 "테스트 통과" 기록
```

#### 계층 2: IDE Hook 자동화 (~95% 신뢰)

**Claude Code** (SessionStart hook):

```json
// .claude/settings.json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "mcp__mem-mesh__.*",
      "hooks": [{
        "type": "command",
        "command": "echo 'mem-mesh tool used' >> /tmp/mem-mesh.log"
      }]
    }]
  }
}
```

> 주의: Claude Code hook은 MCP 도구를 직접 호출할 수 없음. 셸 사이드이펙트만 가능. 결국 CLAUDE.md에 "session_resume을 대화 시작 시 호출하라"고 지시하는 방식에 의존.

**Kiro** (이벤트 드리븐 Hook):

```
파일 저장 시 → Hook → mem-mesh API 직접 호출 (가장 자동화에 가까움)
Git 커밋 시 → Hook → 커밋 내용 자동 저장
```

#### 계층 3: 규칙 파일 지시 (~80% 신뢰)

각 도구별 최적화된 프롬프트 스니펫 제공:

```
docs/integrations/
├── claude-code.md       # CLAUDE.md에 복붙할 내용
├── cursor.md            # .cursorrules에 복붙할 내용
├── kiro.md              # Steering + Hook 설정 가이드
├── antigravity.md       # .antigravity/rules.md + Knowledge Items 병행 가이드
└── windsurf.md          # Rules 지시 (한계 명시)
```

**예시 — CLAUDE.md용 지시:**

```markdown
## mem-mesh 메모리 관리 규칙
- 대화 시작 시 반드시 `mcp__mem-mesh__session_resume`을 호출하세요.
- 중요한 결정, 버그 해결, 교훈은 `mcp__mem-mesh__add`로 저장하세요.
- 대화 종료 시 `mcp__mem-mesh__session_end`를 호출하세요.
```

**예시 — Antigravity용 지시:**

```markdown
## mem-mesh 병행 사용
Antigravity의 Knowledge Items는 이 IDE 안에서만 유효합니다.
다른 도구에서도 활용할 중요한 결정/교훈은
mcp__mem-mesh__add를 통해 저장하세요.
```

### 6.6 서버 사이드 개선 (도구 무관, 100% 효과)

LLM 호출 여부와 관계없이, **도구가 호출됐을 때 더 좋은 응답을 반환**하는 개선:

| 개선 | 설명 | 효과 |
|------|------|------|
| `session_resume` 응답 강화 | 미완료 핀 수, 마지막 활동 시간, 활용 통계 포함 | 사용 가치 체감 |
| `search` 활용도 표시 | "이 메모리는 N번 검색됨" 메타데이터 추가 | 메모리 가치 가시화 |
| `session_end` 핀 기반 요약 | LLM 없이 핀 내용 집계 → 구조화된 요약 | 세션 기록 자동화 |
| `weekly_review` 강화 | zero_result_queries 부각, 지식 갭 시각화 | 지속적 개선 유도 |

---

## 7. 제품 개선 계획

### 7.1 설치 경험 개선

**현재 (마찰 높음):**

```bash
git clone ... && cd mem-mesh && pip install -e .
cp .env.example .env
# 모델 다운로드 대기 (수 분)
# claude_desktop_config.json 수동 편집
```

**목표:**

```bash
pip install mem-mesh
mem-mesh setup          # 대화형: 어떤 AI 도구 쓰세요? → 자동 설정
mem-mesh start          # 서버 시작 + "✅ Claude Desktop에 연결됨"
```

**구체적 작업:**

- [ ] `mem-mesh` CLI 엔트리포인트 추가 (`setup`, `start`, `status`, `doctor` 서브커맨드)
- [ ] `setup` 명령이 AI 도구 감지 → MCP 설정 파일에 자동 등록
- [ ] 첫 실행 시 모델을 백그라운드 다운로드 (프로그레스바)
- [ ] `doctor` 명령으로 설정 상태 진단

### 7.2 도구 표면 계층화 (Progressive Disclosure)

**현재:** 15개 도구 동시 노출 → 학습 부담

**개선:** 설정으로 도구 레벨 선택 가능

```python
# MEM_MESH_TOOL_LEVEL=essential|extended|full

ESSENTIAL_TOOLS = [         # Day 1 (4개)
    "add",
    "search",
    "session_resume",
    "session_end",
]

EXTENDED_TOOLS = [          # Week 1 (6개 추가)
    "pin_add",
    "pin_complete",
    "pin_promote",
    "stats",
    "weekly_review",
    "context",
]

ADVANCED_TOOLS = [          # 필요 시 (5개 추가)
    "link",
    "unlink",
    "get_links",
    "batch_operations",
    "update",
    "delete",
]
```

### 7.3 가치 가시화 (Impact Metrics)

**문제:** 사용자가 "이게 나한테 도움이 됐나?"를 모름

**개선: `session_resume` 응답에 영향도 요약 추가**

```json
{
  "session": { "..." },
  "pins": [ "..." ],
  "impact_summary": {
    "total_memories": 142,
    "memories_recalled_this_week": 37,
    "top_recalled_memory": "DB 마이그레이션 시 반드시 백업 먼저",
    "knowledge_gaps": ["테스트 커버리지 관련 검색 3회 실패"]
  }
}
```

**Dashboard 추가:**

- "이번 주 AI가 참조한 기억 Top 5"
- "메모리 활용 트렌드 차트"
- "지식 갭 (검색했지만 결과 없었던 것)"

### 7.4 카테고리 확장

기존 7개 + 2개 추가:

```python
CATEGORIES = [
    "task",          # 기본 작업
    "bug",           # 버그/이슈
    "idea",          # 아이디어
    "decision",      # 아키텍처/비즈니스 결정
    "incident",      # 장애/사건
    "code_snippet",  # 코드 예제
    "git-history",   # Git 커밋 기록
    "learning",      # [NEW] 교훈, 실수에서 배운 것
    "playbook",      # [NEW] 프로젝트 규약, 반복 패턴
]
```

### 7.5 session_resume에 learning 자동 포함

```python
async def session_resume(project_id: str, ...):
    session = await get_active_session(project_id)
    pins = await get_open_pins(session.id)

    # [NEW] 해당 프로젝트의 learning/playbook 메모리 검색
    learnings = await search(
        query="",
        project_id=project_id,
        category=["learning", "playbook"],
        limit=5,
        sort_by="importance"  # 또는 recall_count
    )

    return {
        "session": session,
        "pins": pins,
        "learnings": learnings,       # [NEW]
        "impact_summary": { ... },    # [NEW]
    }
```

### 7.6 CLI 도구 (MCP 밖 자동화)

```
mem-mesh CLI
├── mem-mesh setup                    # 대화형 설정
├── mem-mesh start                    # 서버 시작
├── mem-mesh status                   # 상태 확인
├── mem-mesh doctor                   # 설정 진단
├── mem-mesh add --content "..." --category learning  # 직접 메모리 추가
├── mem-mesh search "쿼리"             # 직접 검색
├── mem-mesh git-hook install          # Git hook 자동 설치
├── mem-mesh watch --project my-app    # 파일 워처 (향후)
└── mem-mesh wrap "npm test"           # 명령어 래퍼 (향후)
```

---

## 8. 수익 모델

### 8.1 원칙

- **코어는 무료 유지** (MIT 라이선스 이미 공개, 신뢰 깨면 안 됨)
- 단순 호스팅 SaaS로 Mem0와 정면 경쟁하지 않음
- 개인 개발자는 무료, **팀 기능에서 수익 창출**

### 8.2 티어 구조

```
┌─────────────────────────────────────────────────┐
│  Community Edition (무료, MIT)                    │
│                                                   │
│  - 단일 사용자, 로컬 SQLite                         │
│  - 15개 MCP 도구 전체                               │
│  - Web Dashboard                                  │
│  - 무제한 메모리                                    │
│  - CLI 도구                                        │
│  - Git hook 자동화                                  │
├─────────────────────────────────────────────────┤
│  Team Edition (월 $9/user, 유료)                   │
│                                                   │
│  - 공유 메모리 서버 (팀원 간 지식 공유)                 │
│  - RBAC (역할별 접근 제어)                           │
│  - 감사 로그 (누가 무엇을 기억시켰나)                   │
│  - 팀 대시보드 + 팀 활용 분석                          │
│  - 프로젝트 간 메모리 동기화                           │
│  - 팀 onboarding: 신규 멤버가 팀 기억 즉시 접근         │
├─────────────────────────────────────────────────┤
│  Enterprise Edition (문의, 연간 계약)                │
│                                                   │
│  - SSO/SAML 통합                                   │
│  - 데이터 보관 정책 (Retention)                      │
│  - 온프레미스 배포 지원                               │
│  - SLA + 기술 지원                                  │
│  - 컴플라이언스 (SOC2, 데이터 거주지)                  │
└─────────────────────────────────────────────────┘
```

### 8.3 팀 기능이 핵심인 이유

개인 개발자의 지불 의사(WTP)는 낮음. 팀은 다름:

```
개발자 A: 버그 해결책을 mem-mesh에 저장
    ↓
개발자 B: 같은 코드 작업 시, AI가 A의 해결책을 자동 참조
    ↓
팀 전체의 "집단 기억" 형성
```

이건 Confluence/Notion의 "아무도 문서를 안 씀" 문제를 해결 — AI가 자동으로 지식 축적.

### 8.4 보조 수익원

| 모델 | 설명 | 시기 |
|------|------|------|
| Managed Hosting | mem-mesh Cloud (Docker 원클릭 배포) | Phase 2 |
| 프리미엄 임베딩 | 더 큰/정확한 모델 제공 (E5-large 등) | Phase 2 |
| 마켓플레이스 | 도메인별 플러그인 (법률, 의료 용어사전) | Phase 3 |
| 컨설팅 | 기업 도입 + 커스터마이징 | 즉시 가능 |

---

## 9. 사용자 확보 및 성장

### 9.1 즉시 실행 (비용 $0, 효과 최대)

| 작업 | 예상 효과 | 소요 |
|------|---------|------|
| **Awesome MCP Servers에 PR 제출** | 발견성 10배 | 1시간 |
| **LobeHub 마켓플레이스 등록** | 새로운 유입 채널 | 2시간 |
| **GitHub README에 30초 데모 GIF** | 전환율 향상 | 2시간 |
| **한국어 블로그 (velog/tistory)** | 한국 시장 선점 | 반나절 |
| **영문 블로그 (dev.to/medium)** | 글로벌 인지도 | 반나절 |
| **npm 래퍼 패키지 (`npx mem-mesh`)** | Node.js 개발자 접근 | 1일 |

> **가장 중요:** 지금 당장 코드를 더 짜는 것보다 **레지스트리 등록 + 데모 GIF + Before/After 시나리오**가 더 많은 사용자를 가져옴. 기능은 이미 충분함. 문제는 아무도 모른다는 것.

### 9.2 README 리뉴얼

현재 README는 기능 나열 중심. **Before/After 시나리오**로 전환:

```markdown
## 왜 mem-mesh인가?

### Before (mem-mesh 없이)
- 어제 Claude에게 설명한 프로젝트 규약을 오늘 다시 설명
- Cursor에서 해결한 버그를 Claude Code에서 또 해결
- 3개월 전 결정한 아키텍처 이유를 아무도 기억 못함

### After (mem-mesh와 함께)
- 세션 시작 시 자동으로 이전 맥락 로드
- 어떤 AI 도구든 같은 기억 공유
- "왜 이렇게 했지?" → 즉시 검색
```

### 9.3 한국 시장 전략

mem-mesh의 한국어 최적화는 경쟁자 중 유일. 한국 시장을 교두보로 삼아야 함.

**타겟 채널:**

| 채널 | 대상 | 콘텐츠 |
|------|------|--------|
| velog | 한국 개발자 | "AI 코딩 도구에 기억력을 달아주기" |
| GeekNews | 얼리어답터 | 프로젝트 소개 + 데모 |
| Cursor Korea 커뮤니티 | Cursor 사용자 | Cursor + mem-mesh 통합 가이드 |
| Claude Code 사용자 | Claude Code 유저 | CLAUDE.md 템플릿 제공 |

### 9.4 콘텐츠 전략

| 콘텐츠 | 목적 | 빈도 |
|--------|------|------|
| 사용 가이드 (도구별) | 설치 → 첫 사용 | 도구당 1편 |
| 사용 사례 (시나리오별) | "이런 상황에서 유용" | 월 1편 |
| 릴리즈 노트 | 업데이트 알림 | 릴리즈마다 |
| 비교 글 | "mem-mesh vs Mem0" | 분기 1편 |

---

## 10. 실행 로드맵

### Phase 0: 즉시 실행 (지금 ~ 2주)

**목표: 발견성 확보 + 벤치마크 기반 마련**

비용: ~$50 (LLM API), 코드 변경 최소

- [ ] Awesome MCP Servers에 PR 제출
- [ ] LobeHub 마켓플레이스 등록
- [ ] GitHub README에 30초 데모 GIF 추가
- [ ] README를 Before/After 시나리오로 리뉴얼
- [ ] 한국어 블로그 1편 (velog)
- [ ] 영문 블로그 1편 (dev.to)
- [ ] `learning`, `playbook` 카테고리 추가 (30분 작업)
- [ ] LongMemEval 환경 구축 + 어댑터 MVP 작성
- [ ] 영어 벤치마크 1차 실행 (현재 검색 파이프라인 기준선 확보)

### Phase 1: 핵심 경험 개선 (1개월)

**목표: 설치 마찰 제거 + 가치 체감 + 벤치마크 공개**

- [ ] LongMemEval 검색 튜닝 (top_k, RRF 가중치, 인덱싱 전략)
- [ ] 한국어 질문 번역 (500개) + 한국어 벤치마크 실행
- [ ] README에 벤치마크 결과 섹션 추가
- [ ] CLI 엔트리포인트: `mem-mesh setup`, `mem-mesh start`, `mem-mesh status`
- [ ] `mem-mesh setup`이 AI 도구 감지 → MCP 자동 등록
- [ ] 도구 레벨 분리 (`MEM_MESH_TOOL_LEVEL=essential|extended|full`)
- [ ] `session_resume` 응답에 impact_summary 추가
- [ ] `session_resume`에 learning/playbook 메모리 자동 포함
- [ ] `search` 결과에 활용도 메타데이터 추가 (recall_count)
- [ ] 도구별 통합 가이드 작성 (docs/integrations/)
  - [ ] Claude Code + CLAUDE.md 템플릿
  - [ ] Cursor + .cursorrules 템플릿
  - [ ] Kiro + Hook 설정 가이드
  - [ ] Antigravity + Knowledge Items 병행 가이드
  - [ ] Windsurf + Rules 가이드
- [ ] npm 래퍼 패키지 (`npx mem-mesh`)

### Phase 2: 자동화 + 성장 (1~3개월)

**목표: MCP 밖 자동화 + 사용자 기반 확대**

- [ ] `mem-mesh git-hook install` — Git post-commit hook 자동 설치
- [ ] `session_end` 시 핀 기반 구조화된 요약 자동 생성
- [ ] `weekly_review` 강화 (지식 갭 시각화, 활용 트렌드)
- [ ] Dashboard에 활용도 차트 추가 ("AI가 참조한 기억 Top 5")
- [ ] 검색 메트릭 수집 강화 (recall_count 자동 추적)
- [ ] 사용 사례 블로그 시리즈 (월 1편)
- [ ] 커뮤니티 채널 개설 (Discord 또는 GitHub Discussions)

### Phase 3: 팀 기능 + 수익화 (3~6개월)

**목표: 팀 에디션 출시 → 수익 시작**

- [ ] 공유 메모리 서버 (멀티 유저 지원)
- [ ] RBAC (역할별 접근 제어)
- [ ] 감사 로그 (누가 무엇을 기억시켰나)
- [ ] 팀 대시보드 + 팀 활용 분석
- [ ] Team Edition 유료화 시작
- [ ] Managed Hosting 옵션 (Docker 원클릭)

### Phase 4: 플랫폼 (6개월+)

**목표: 생태계 확장**

- [ ] 다국어 SDK (Node.js, Go)
- [ ] 프리미엄 임베딩 모델 옵션
- [ ] 에이전트 프레임워크 통합 (LangGraph, CrewAI)
- [ ] 마켓플레이스 (도메인별 플러그인)
- [ ] Enterprise Edition

---

## 11. OMEGA Memory 경쟁 전략

### 11.1 OMEGA 분석

OMEGA Memory는 현재 mem-mesh의 가장 직접적인 경쟁자.

| 항목 | OMEGA | mem-mesh |
|------|-------|---------|
| **도구 수** | 25개 | 15개 |
| **벤치마크** | LongMemEval 95.4% 주장 | 미측정 |
| **설치** | `pip install omega-memory && omega setup` | pip install + 수동 설정 |
| **자동 캡처** | Git hook (Claude Code 전용) | 미구현 |
| **임베딩** | bge-small-en-v1.5 (영어 전용) | all-MiniLM-L6-v2 (다국어) |
| **한국어** | X (영어 임베딩 모델) | **O (n-gram FTS, 한영 검색)** |
| **라이선스** | Apache 2.0 | MIT |
| **세션/핀** | X | **O (고유 워크플로우)** |
| **대시보드** | X | **O (웹 UI)** |
| **배치 연산** | X | **O (30-50% 토큰 절감)** |

### 11.2 4축 경쟁 전략

#### 축 1: DX 격차 해소 (Parity)

OMEGA의 `omega setup` CLI는 즉각적인 DX 우위. 이를 따라잡아야 함.

| OMEGA 강점 | mem-mesh 대응 | 우선순위 |
|-----------|-------------|---------|
| `omega setup` 원커맨드 | `mem-mesh setup` CLI 구현 | **P0** |
| 25개 도구 | 15개 유지 (Progressive Disclosure로 차별화) | P2 |
| LongMemEval 95.4% | 벤치마크 실행 + 공개 (섹션 12 참조) | **P0** |

#### 축 2: 고유 차별화 강화 (Differentiation)

OMEGA에 없는 mem-mesh 고유 강점을 부각.

| mem-mesh 고유 | 가치 | OMEGA 대응 불가 이유 |
|-------------|------|------------------|
| **한국어 최적화** | 한국 시장 독점 | bge-small-en-v1.5는 영어 전용 |
| **웹 대시보드** | 메모리 시각화/관리 | CLI만 제공 |
| **세션/핀 워크플로우** | 작업 흐름 관리 | 기본 CRUD만 |
| **배치 연산** | 토큰 30-50% 절감 | 미지원 |
| **팀 기능 (Phase 3)** | 집단 기억 | 개인용만 |

#### 축 3: 기능 흡수 (Absorption)

OMEGA의 인기 기능을 mem-mesh에도 구현.

| OMEGA 기능 | mem-mesh 구현 | 난이도 |
|-----------|-------------|--------|
| Git hook 자동 캡처 | `mem-mesh git-hook install` | Low |
| 벤치마크 공개 | LongMemEval 실행 (섹션 12) | Medium |
| `omega setup` CLI | `mem-mesh setup` | Medium |

#### 축 4: 블루 오션 선점 (Blue Ocean)

OMEGA가 아직 진입하지 않은 영역.

| 영역 | 설명 | 시기 |
|------|------|------|
| **팀 메모리** | 팀원 간 지식 공유, RBAC | Phase 3 |
| **크로스 툴 허브** | Cursor+Claude+Kiro+Antigravity 통합 | Phase 1 |
| **한국어 시장** | 한국 개발자 커뮤니티 선점 | Phase 0 |
| **Enterprise** | SSO, 감사 로그, 데이터 보관 정책 | Phase 4 |

### 11.3 벤치마크 대응 전략

OMEGA의 "LongMemEval 95.4%" 주장은 강력한 마케팅 무기. mem-mesh도 반드시 벤치마크를 공개해야 함.

**시나리오별 대응:**

| mem-mesh 점수 | 전략 |
|-------------|------|
| **> 95%** | 정면 비교: "OMEGA보다 높은 정확도" |
| **90~95%** | "동급 정확도 + 한국어 + 대시보드 + 팀 기능" |
| **80~90%** | 검색 파이프라인 개선 후 재측정 |
| **< 80%** | 검색 엔진 근본적 개선 필요 (임베딩 모델, RRF 가중치 등) |

**핵심:** 한국어 벤치마크에서 OMEGA를 압도하는 것이 전략적으로 더 가치 있음 (영어에서 동급이면 충분).

---

## 12. LongMemEval 벤치마킹 계획

### 12.1 LongMemEval 개요

**LongMemEval** — ICLR 2025 발표, 장기 대화형 메모리 시스템의 표준 벤치마크.

- **논문:** "LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory" (ArXiv: 2410.10813)
- **데이터셋:** [HuggingFace](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
- **코드:** [GitHub](https://github.com/xiaowu0162/LongMemEval)
- **라이선스:** MIT

### 12.2 벤치마크 구조

#### 5가지 핵심 메모리 능력

| 메모리 능력 | 질문 유형 | 설명 |
|-----------|---------|------|
| **정보 추출** | single-session-user, single-session-assistant, single-session-preference | 단일 세션에서 사용자/어시스턴트가 언급한 사실 회상 |
| **멀티 세션 추론** | multi-session | 여러 세션에 흩어진 정보 종합 |
| **지식 업데이트** | knowledge-update | 시간에 따른 정보 변경 인식 (예: 사용자 이사) |
| **시간 추론** | temporal-reasoning | 타임스탬프, 날짜, 시간 관계 추론 |
| **기권** | *_abs (모든 유형 변형) | 답할 수 없는 질문 식별 |

#### 데이터셋 규모

| 항목 | 수치 |
|------|------|
| 총 질문 수 | 500개 (수작업 큐레이션) |
| 데이터셋 변형 | oracle (증거만) / S (~40세션, ~115K토큰) / M (~500세션, ~1.5M토큰) |
| 세션 구성 | ~50% 사용자 고유 + ~25% ShareGPT 필러 + ~25% UltraChat 필러 |

#### 데이터 형식

```json
{
  "question_id": "q_001",
  "question_type": "single-session-user",
  "question": "What is the name of Alice's dog?",
  "answer": "Buddy",
  "question_date": "2024/06/15 (Saturday) 10:00",
  "haystack_dates": ["2024/03/15 (Friday) 14:30", "..."],
  "haystack_session_ids": ["session_001", "session_002", "..."],
  "haystack_sessions": [
    [
      {"role": "user", "content": "I just adopted a dog named Buddy!"},
      {"role": "assistant", "content": "That's wonderful! What breed is Buddy?"}
    ],
    "..."
  ],
  "answer_session_ids": ["session_042"]
}
```

#### 평가 방법

- **QA 평가:** GPT-4o가 judge (질문 유형별 특화 프롬프트)
- **출력 형식:** JSONL (`{"question_id": "q_001", "hypothesis": "Buddy"}`)
- **메트릭:** 카테고리별 정확도, 태스크 평균 정확도, 전체 정확도, 기권 정확도
- **검색 메트릭:** recall_any@k, recall_all@k, ndcg_any@k (k=1,3,5,10,30,50)

#### 기존 베이스라인

| 시스템 | 정확도 | 비고 |
|--------|-------|------|
| GPT-4o (Oracle) | 87.0% | 증거 세션만 제공 |
| GPT-4o (LongMemEval_S) | 60.6% | ~115K 토큰 전체 입력 |
| RAG + Fact Expansion + CoN | ~72% | 최적화된 RAG 파이프라인 |
| OMEGA Memory (주장) | 95.4% | 자체 측정, 미검증 |
| ChatGPT (GPT-4o) | 57.7% | 상용 서비스 |

### 12.3 mem-mesh 벤치마킹 아키텍처

mem-mesh는 MCP 도구 서버이므로, LongMemEval의 3단계 파이프라인(인덱싱→검색→생성)에 맞는 어댑터가 필요.

```
┌──────────────────────────────────────────────────────┐
│  LongMemEval Adapter (benchmark_runner.py)            │
│                                                        │
│  Phase 1: Indexing                                     │
│  ┌──────────────────────────────────────────────────┐ │
│  │ haystack_sessions → mem-mesh add() 호출           │ │
│  │ - 세션 단위 또는 턴 단위로 메모리 생성               │ │
│  │ - haystack_dates를 메타데이터로 저장               │ │
│  │ - session_id를 tags에 포함                        │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  Phase 2: Retrieval                                    │
│  ┌──────────────────────────────────────────────────┐ │
│  │ question → mem-mesh search() 호출                 │ │
│  │ - 하이브리드 검색 (RRF: 벡터 + FTS5)               │ │
│  │ - top-k 결과 수집                                  │ │
│  │ - 검색 메트릭 수집 (recall@k, ndcg@k)             │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  Phase 3: Generation                                   │
│  ┌──────────────────────────────────────────────────┐ │
│  │ question + retrieved_memories → LLM (Claude/GPT)  │ │
│  │ - 답변 생성                                        │ │
│  │ - JSONL 출력: {question_id, hypothesis}            │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  Phase 4: Evaluation                                   │
│  ┌──────────────────────────────────────────────────┐ │
│  │ evaluate_qa.py (GPT-4o judge) → 정확도 리포트      │ │
│  └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### 12.4 실행 계획

#### Variant 1: 영어 원안 (English Baseline)

LongMemEval 데이터셋을 그대로 사용.

**목적:** OMEGA와 직접 비교 가능한 수치 확보.

**단계:**

| Step | 작업 | 상세 |
|------|------|------|
| 1 | 환경 구축 | LongMemEval 클론, 데이터셋 다운로드 (HuggingFace) |
| 2 | 어댑터 스크립트 작성 | `benchmarks/longmemeval/adapter.py` |
| 3 | 인덱싱 전략 결정 | 세션 단위 vs 턴 단위 (둘 다 실험) |
| 4 | 인덱싱 실행 | 각 질문의 haystack_sessions → mem-mesh 메모리로 변환 |
| 5 | 검색 실행 | 500개 질문 × mem-mesh search → top-k 결과 수집 |
| 6 | 검색 메트릭 측정 | recall@k, ndcg@k (LongMemEval 스크립트 활용) |
| 7 | 답변 생성 | retrieved context + question → Claude/GPT-4o → hypothesis |
| 8 | QA 평가 | evaluate_qa.py → 카테고리별 정확도 |
| 9 | 결과 분석 | OMEGA 대비, 기존 베이스라인 대비 비교 |

**인덱싱 전략 (실험 변수):**

| 전략 | 설명 | 장점 | 단점 |
|------|------|------|------|
| **세션 단위** | 1 세션 = 1 메모리 (content: 전체 대화) | 문맥 보존 | content 길 수 있음 (10K자 제한) |
| **턴 단위** | 1 턴 = 1 메모리 (user+assistant 쌍) | 정밀 검색 | 문맥 손실 |
| **세션 + 팩트 추출** | 세션 텍스트 + 추출된 핵심 사실 (별도 메모리) | 검색 정밀도 향상 | LLM 호출 필요 (비용) |
| **슬라이딩 윈도우** | 3~5턴 윈도우로 청킹 | 균형 | 구현 복잡 |

**검색 파라미터 (튜닝 변수):**

| 파라미터 | 기본값 | 탐색 범위 | 설명 |
|---------|--------|---------|------|
| top_k | 5 | 3, 5, 10, 20 | 검색 결과 수 |
| text_weight | 1.2 | 0.8~2.0 | RRF FTS5 가중치 |
| vector_weight | 1.0 | 0.8~1.5 | RRF 벡터 가중치 |
| search_mode | hybrid | hybrid, semantic, exact | 검색 모드 |
| similarity_threshold | 0.3 | 0.1~0.5 | 벡터 유사도 임계값 |

**생성 모델 (비교 대상):**

| 모델 | 비용 | 목적 |
|------|------|------|
| claude-sonnet-4-20250514 | 중간 | 주력 평가 |
| gpt-4o | 중간 | OMEGA와 동일 조건 비교 |
| claude-haiku-4-5-20251001 | 낮음 | 비용 효율 평가 |

#### Variant 2: 한국어 번역 (Korean Benchmark)

mem-mesh의 한국어 최적화 강점을 증명하는 핵심 벤치마크.

**목적:** OMEGA(영어 전용 임베딩)가 구조적으로 불리한 영역에서 우위 증명.

**번역 범위 옵션:**

| 옵션 | 번역 대상 | 장점 | 단점 | 권장 |
|------|---------|------|------|------|
| **A: 질문만 번역** | question, answer | 빠른 실행, 크로스링구얼 검색 테스트 | haystack은 영어 (비현실적) | 1차 |
| **B: 질문 + 핵심 세션** | question, answer, answer_sessions | 핵심 매칭 테스트 | 필러 세션은 영어 | 2차 |
| **C: 전체 번역** | 모든 세션 + 질문 | 완전한 한국어 평가 | 번역 비용 높음 (~1.5M 토큰) | 최종 |

**번역 파이프라인:**

```
원본 데이터셋 (영어)
    ↓
[Phase 1] 질문 + 정답 번역 (500쌍)
    │   도구: Claude Sonnet (일괄 번역)
    │   검수: 한국어 네이티브 리뷰 (샘플 50개)
    ↓
[Phase 2] answer_sessions 번역 (증거 세션만)
    │   도구: Claude Sonnet (대화체 번역)
    │   주의: 대화 자연스러움 유지, 사실 정보 보존
    ↓
[Phase 3] 전체 haystack 번역 (선택)
    │   도구: Claude/GPT-4o 배치 API
    │   비용: ~$50-100 (1.5M 토큰 기준)
    ↓
번역 데이터셋 (한국어)
    ↓
benchmarks/longmemeval/data/longmemeval_ko.json
```

**한국어 번역 품질 기준:**

| 기준 | 설명 | 예시 |
|------|------|------|
| 자연스러움 | 번역투 아닌 자연스러운 한국어 대화 | "I adopted a dog" → "강아지를 입양했어" (O) / "나는 개를 입양했습니다" (X) |
| 사실 보존 | 고유명사, 숫자, 날짜 정확히 보존 | "Buddy" → "버디" (음역 유지) |
| 문화 적응 | 한국어 맥락에 맞는 자연스러운 변환 | 달러→원 변환 불필요 (사실 보존 우선) |
| 일관성 | 같은 엔티티를 같은 이름으로 번역 | 한 세트 내에서 통일 |

**한국어 벤치마크에서 기대되는 mem-mesh 우위:**

| 영역 | mem-mesh | OMEGA | 이유 |
|------|---------|-------|------|
| 한국어 FTS | **O** (n-gram 인덱싱) | X (영어 토크나이저) | 한국어 형태소 처리 |
| 한국어 임베딩 | **중간** (다국어 모델) | **낮음** (bge-small-en-v1.5) | 영어 전용 임베딩은 한국어 벡터 품질 낮음 |
| 한영 혼용 검색 | **O** (쿼리 확장) | X | 한국어 질문 + 영어 문서 크로스 검색 |
| 한국어 정규화 | **O** (sigmoid) | X | 한국어 검색 점수 정규화 |

### 12.5 어댑터 구현 상세

#### 파일 구조

```
benchmarks/
└── longmemeval/
    ├── README.md                     # 벤치마크 실행 가이드
    ├── adapter.py                    # 메인 어댑터 (인덱싱 + 검색 + 생성)
    ├── indexer.py                    # mem-mesh 인덱싱 전략
    ├── retriever.py                  # mem-mesh 검색 래퍼
    ├── generator.py                  # LLM 답변 생성
    ├── translator.py                 # 한국어 번역 스크립트
    ├── evaluate.py                   # 평가 실행 + 리포트 생성
    ├── config.yaml                   # 실험 설정 (모델, top_k, 가중치 등)
    ├── results/                      # 실험 결과
    │   ├── en_session_level.jsonl    # 영어 세션 단위 결과
    │   ├── en_turn_level.jsonl       # 영어 턴 단위 결과
    │   ├── ko_question_only.jsonl    # 한국어 질문만 번역 결과
    │   └── ko_full.jsonl            # 한국어 전체 번역 결과
    └── data/
        ├── longmemeval_s.json        # 원본 (HuggingFace 다운로드)
        └── longmemeval_ko.json       # 한국어 번역본
```

#### 어댑터 핵심 로직 (의사코드)

```python
class MemMeshLongMemEvalAdapter:
    """LongMemEval ↔ mem-mesh 연동 어댑터"""

    def __init__(self, config):
        self.mem_service = MemoryService(...)   # mem-mesh 직접 호출
        self.search_service = UnifiedSearchService(...)
        self.llm = LLMClient(config.model)      # 답변 생성용

    async def run_benchmark(self, dataset_path, output_path):
        dataset = load_json(dataset_path)
        results = []

        for item in dataset:
            # 1. 새 프로젝트 컨텍스트 생성 (질문 간 격리)
            project_id = f"longmemeval_{item['question_id']}"

            # 2. 인덱싱: haystack_sessions → mem-mesh memories
            await self.index_sessions(
                project_id,
                item['haystack_sessions'],
                item['haystack_dates']
            )

            # 3. 검색: question → mem-mesh search
            retrieved = await self.search_service.search(
                query=item['question'],
                project_id=project_id,
                limit=self.config.top_k,
                mode="hybrid"
            )

            # 4. 생성: retrieved + question → LLM → hypothesis
            hypothesis = await self.generate_answer(
                question=item['question'],
                question_date=item['question_date'],
                retrieved_memories=retrieved
            )

            results.append({
                "question_id": item['question_id'],
                "hypothesis": hypothesis,
                "retrieval_results": self.format_retrieval(retrieved, item)
            })

            # 5. 정리: 다음 질문을 위해 프로젝트 메모리 삭제
            await self.cleanup(project_id)

        save_jsonl(results, output_path)

    async def index_sessions(self, project_id, sessions, dates):
        """세션을 mem-mesh 메모리로 변환"""
        for i, (session, date) in enumerate(zip(sessions, dates)):
            if self.config.indexing == "session":
                # 세션 전체를 하나의 메모리로
                content = self.format_session(session)
                await self.mem_service.add(
                    content=content[:10000],  # mem-mesh 제한
                    project_id=project_id,
                    category="task",
                    tags=[f"session_{i}", date]
                )
            elif self.config.indexing == "turn":
                # 각 턴을 개별 메모리로
                for j, turn in enumerate(session):
                    content = f"[{turn['role']}] {turn['content']}"
                    await self.mem_service.add(
                        content=content,
                        project_id=project_id,
                        category="task",
                        tags=[f"session_{i}", f"turn_{j}", date]
                    )
```

### 12.6 실행 로드맵

| 단계 | 작업 | 예상 소요 | 비용 |
|------|------|---------|------|
| **1. 환경 구축** | LongMemEval 클론, 데이터셋 다운로드, 의존성 설치 | 2시간 | $0 |
| **2. 어댑터 MVP** | adapter.py 기본 구현 (세션 단위 인덱싱) | 1일 | $0 |
| **3. 영어 벤치마크 실행** | 500개 질문 × (인덱싱 + 검색 + 생성 + 평가) | 2~4시간 (실행) | ~$20-50 (LLM API) |
| **4. 검색 튜닝** | top_k, 가중치, 인덱싱 전략 실험 (5~10회 반복) | 2일 | ~$100-200 |
| **5. 한국어 번역 (질문)** | 500개 질문 + 정답 번역 + 검수 | 1일 | ~$10-20 |
| **6. 한국어 벤치마크 실행** | 번역된 질문으로 벤치마크 재실행 | 2~4시간 | ~$20-50 |
| **7. 한국어 haystack 번역** | answer_sessions 번역 (선택) | 2~3일 | ~$50-100 |
| **8. 결과 분석 + 리포트** | 카테고리별 분석, OMEGA 비교, 블로그 작성 | 1일 | $0 |
| **총합** | | **~1주** | **~$200-400** |

### 12.7 결과 활용 계획

#### 벤치마크 결과 공개

```markdown
## README.md 추가 섹션

### Benchmark Results (LongMemEval)

| Benchmark | mem-mesh | OMEGA | GPT-4o (RAG) |
|-----------|---------|-------|-------------|
| English (Overall) | X.X% | 95.4% | 61.5% |
| Korean (Overall) | X.X% | N/A | N/A |
| Info Extraction | X.X% | - | - |
| Multi-Session | X.X% | - | - |
| Knowledge Update | X.X% | - | - |
| Temporal Reasoning | X.X% | - | - |
| Abstention | X.X% | - | - |

Evaluated using [LongMemEval](https://github.com/xiaowu0162/LongMemEval) (ICLR 2025).
```

#### 블로그/마케팅 활용

| 시나리오 | 헤드라인 | 타겟 |
|---------|---------|------|
| 영어에서 OMEGA 초과 | "mem-mesh beats OMEGA on LongMemEval" | 글로벌 |
| 영어에서 동급 | "Same accuracy, better DX: Korean support + Dashboard + Team features" | 글로벌 |
| 한국어에서 압도 | "한국어 메모리 정확도 X% — 유일한 한국어 최적화 MCP 메모리" | 한국 |

#### 검색 파이프라인 개선 피드백 루프

벤치마크 결과를 검색 엔진 개선에 직접 활용:

```
벤치마크 실행 → 카테고리별 정확도 분석
    ↓
약점 카테고리 식별 (예: temporal-reasoning 60%)
    ↓
검색 파이프라인 개선 (예: 날짜 메타데이터 필터 추가)
    ↓
재측정 → 개선 확인
    ↓
반복
```

### 12.8 기술적 고려사항

#### mem-mesh 제약과 대응

| 제약 | 영향 | 대응 |
|------|------|------|
| content 최대 10,000자 | 긴 세션 잘림 | 세션 분할 또는 요약 (LLM) |
| LLM 미내장 | 자동 팩트 추출 불가 | 외부 LLM으로 전처리 (인덱싱 시) |
| 시간 메타데이터 | 메모리에 날짜 필드 없음 | tags에 날짜 포함, content에 명시 |
| 프로젝트 간 격리 | 질문별 별도 프로젝트 필요 | project_id로 격리 → 완료 후 삭제 |

#### 임베딩 모델 실험

벤치마크를 기회로 삼아 임베딩 모델도 비교:

| 모델 | 차원 | 한국어 | 크기 | 비고 |
|------|------|--------|------|------|
| all-MiniLM-L6-v2 (현재) | 384 | 제한적 | 80MB | 현재 기본 |
| bge-m3 | 1024 | **우수** | 2.3GB | 다국어 최강 |
| multilingual-e5-large | 1024 | 우수 | 1.1GB | 밸런스 |
| bge-small-en-v1.5 (OMEGA) | 384 | **X** | 130MB | 영어 전용 |

벤치마크 결과에 따라 기본 임베딩 모델 변경 검토.

---

## 부록

### A. 의사결정 원칙

1. **서버 사이드 개선 우선** — 모든 클라이언트에 효과 있는 것 먼저
2. **Git hook > IDE hook > 규칙 지시 > LLM 자율** — 신뢰도 순으로 투자
3. **기능 추가 < 발견성 확보** — 현재 단계에서는 마케팅이 코딩보다 ROI 높음
4. **MCP 도구 서버의 한계 인정** — LLM 미내장, 자율 추론 불가, 수동적 구조

### B. 하지 말 것

- Memory 모델에 `parent_id` 추가 (기존 relations로 충분)
- Small-to-Large 청킹 (해결할 문제 없음)
- 시스템 프롬프트 강제 주입 시도 (MCP에서 불가)
- 코어 유료화 (MIT 신뢰 깨짐)
- Mem0과 SaaS 정면 경쟁 (규모 불리)

### C. 참고 자료

- [Awesome MCP Servers](https://github.com/wong2/awesome-mcp-servers)
- [MCP Protocol Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [Mem0 OpenMemory](https://mem0.ai/blog/introducing-openmemory-mcp)
- [Google Antigravity](https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/)
- [Claude Code Hooks](https://code.claude.com/docs/en/hooks)
- [Kiro Hooks Guide](https://aicodingtools.blog/en/kiro/kiro-hooks-guide)
- [Cursor Hooks Deep Dive](https://blog.gitbutler.com/cursor-hooks-deep-dive)
- [Windsurf Cascade MCP](https://docs.windsurf.com/windsurf/cascade/mcp)
- [LongMemEval Paper](https://arxiv.org/abs/2410.10813) — ICLR 2025, 장기 메모리 벤치마크
- [LongMemEval GitHub](https://github.com/xiaowu0162/LongMemEval) — 벤치마크 코드 + 평가 스크립트
- [LongMemEval Dataset](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) — HuggingFace 데이터셋
- [OMEGA Memory](https://github.com/AidenYangX/omega-memory-mcp) — 직접 경쟁자, LongMemEval 95.4% 주장
