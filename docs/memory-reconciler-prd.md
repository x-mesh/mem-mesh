# Memory Reconciler PRD

**문서 상태:** Proposed
**문서 버전:** 0.2
**대상 시스템:** mem-mesh
**작성 목적:** 장기 기억이 누적되면서 생기는 중복, 구버전, 모순, provenance 손실, 자동 생성 잡음을 LLM 기반으로 판정하고 안전하게 정리하는 제품 계약 정의

---

## 1. 제품 요약

Memory Reconciler는 기존 장기 memory를 읽어 관련 지식을 묶고, 묶음별 대표 memory와 여러 원본을 종합한 정리 본문을 만드는 LLM 기반 유지 시스템이다. observation, session, pin, relation, anchor는 판단 근거로 참조한다. 첫 출시는 해당 원본 기록의 수명주기를 변경하지 않는다.

Reconciler는 기존 memory의 본문, 상태, metadata, relation, anchor를 수정하거나 삭제하지 않는다. 고정된 snapshot에서 정리안을 만들고 별도 SQLite 테이블에 저장한다. 정책과 검증을 통과한 결과만 검색·context에서 활성화한다. `MERGE`·`SUPERSEDE`는 live run에서 category와 관계없이 자동 활성화한다. 명시적으로 보호한 원본은 후보에서 제외한다. 적용은 원본 변경이 아니라 정리 결과의 활성화다.

```text
기존 원본 보존
  → 후보 묶음과 evidence snapshot
  → LLM 관계 판정과 대표 선택
  → 원본 근거를 연결한 새 정리 본문
  → 정책·검증, 필요한 proposal만 승인
  → 정리 결과 활성화
  → 검색·context에서 중복을 접고 정리 결과 반환
  → 활성화된 정리 결과를 종합한 Project Overview
```

대표 memory는 프로젝트 전체를 대표하는 한 개가 아니다. 같은 지식의 후보 묶음에 속한 기존 원본 중 한 개다. 대표는 원본 확인의 기준점이고, 정리 본문은 여러 원본의 사실·조건·예외를 모은 파생 결과다. 검색에서 대표 원본과 정리 본문을 같은 지식의 결과로 중복 노출하지 않는다.

기존 Project Overview 화면은 유지한다. 최근 원본 일부를 직접 요약하던 생성 기반을 활성화된 정리 결과로 교체한다. Overview는 묶음별 정리와 별도의 프로젝트 단위 종합 단계이며, 정리 범위와 미검토 memory를 표시한다.

기본 실행은 dry-run이다. activation-capable run은 현재 canonical인 입력의 `MERGE`·`SUPERSEDE`를 검증 후 자동 활성화한다. `decision`·`incident` category에도 같은 규칙을 적용한다. `reconciler_protected`로 명시한 원본은 후보에서 제외하며, `NEEDS_REVIEW`와 dry-run 결과는 활성화하지 않는다. 자동 잡음 제외와 파생 관계 추가는 별도의 프로젝트 정책을 따른다.

Memory Evolution Loop는 향후 정리 결과를 수집 정책의 개선 신호로 연결하는 상위 운영 구조다. 첫 출시는 장기 memory 정리, 검색·context 반영, Project Overview 통합까지다. 성공은 원본 건수 감소가 아니라 중복 노출 감소, provenance 보존, 의미와 검색 품질 유지다.

---

## 2. 문제 정의

### 2.1 현재 문제

mem-mesh는 서로 다른 경로에서 memory를 수집한다.

- 사용자가 직접 작성한 permanent memory
- hook이 수집한 raw observation
- session 종료 시 생성되는 summary
- pin에서 승격된 memory
- agent 또는 subagent가 생성한 memory
- 외부 relay 또는 hub에서 유입된 memory
- 운영 스크립트와 자동화 loop가 남긴 결과

이 구조는 수집 범위를 넓히지만, 다음 문제가 누적될 수 있다.

- 동일한 결론이 여러 session에서 반복 저장됨
- 내부 agent summary나 prompt가 durable memory로 잘못 승격됨
- `[unknown agent]`처럼 provenance가 불완전한 기록이 쌓임
- 최신 memory가 과거 memory를 대체했는지 명확하지 않음
- 내용이 비슷하지만 실제로는 다른 조건을 가진 memory가 잘못 합쳐짐
- contradiction이 별도의 관계로 표현되지 않고 둘 중 하나가 삭제됨
- anchor가 가리키는 파일과 현재 파일의 상태가 달라짐
- 정리 결과와 원본의 FTS·vector·relation 참조가 어긋남
- 한 번 정리한 잡음이 다음 hook 실행에서 다시 유입됨
- 대량 정리가 운영 스크립트에 의존해 재현성과 감사성이 떨어짐

### 2.2 문제의 본질

문제는 단순한 중복 제거가 아니다. 각 memory가 다음 중 무엇인지 판단해야 한다.

- 동일한 사실의 반복 기록
- 동일한 결정의 최신 버전
- 서로 다른 시점의 유효한 사실
- 조건이 다른 보완 정보
- 실제 모순
- 임시 작업 기록
- 장기적으로 보존할 가치가 없는 자동 생성 잡음
- 현재는 판단할 수 없어 보류해야 하는 정보

이 판단은 문자열 일치만으로 해결할 수 없다. 내용, 시점, project, origin, provenance, anchor, relation, 검색 사용 이력을 함께 읽어야 하며, 의미 판단에는 LLM이 필요하다.

---

## 3. 제품 목표

### 3.1 핵심 목표

#### G1. 의미 기반 정리

중복, 구버전, 잡음, 모순을 판정한다. 관련 memory를 묶고 대표 원본을 선택하며, 여러 원본에서 새 정리 본문을 생성한다. 서로 다른 조건이나 모순을 하나의 사실로 평탄화하지 않는다.

#### G2. 원본과 파생 결과의 분리

기존 canonical memory는 원본 정본으로 유지한다. 정리 결과에는 대표 참조, 종합 본문, claim별 원본 참조와 유효성 정보를 저장한다. 원본 전체를 두 번째 정본으로 복제하지 않는다. curation ledger는 판단·승인·활성화·검증 이력을 저장한다.

#### G3. 비파괴성과 적용 취소

Reconciler는 기존 원본 행을 변경하지 않는다. 적용과 취소는 파생 결과의 활성화 상태를 바꾼다. 취소 후에는 다른 유효한 결과로 여전히 덮이지 않은 원본이 기본 검색 대상이 된다. 취소된 결과에 의존한 Overview는 갱신 필요 상태로 표시한다.

#### G4. 증거와 provenance 보존

대표는 해당 묶음의 원본 중에서만 선택한다. 정리 본문의 핵심 claim을 원본 ID와 판정 당시 버전 또는 hash로 추적한다. 원본의 시점, 조건, 예외, 출처를 보존한다.

#### G5. 재실행 안전성

원본 보존과 멱등성은 별도 요구다. 같은 원본 구성·버전과 같은 처리 정책의 재실행은 중복 결과를 만들지 않는다. 같은 proposal을 반복 승인·적용해도 중복 활성화가 발생하지 않는다.

#### G6. 검색 품질 보호

검색과 context는 같은 활성 정리 결과를 사용한다. 활성화되지 않았거나 무효화된 결과는 사용하지 않는다. 원본 조회와 원본 기반 검색을 제공하고, project·anchor scope와 인용 근거를 유지한다.

#### G7. Project Overview 통합

활성화된 묶음별 정리 결과를 프로젝트 단위로 종합한다. 기존 Overview 화면을 유지하되 생성 기반을 교체하고, 원본 근거·생성 시점·정리 범위·미검토 memory 여부를 표시한다.

#### G8. 운영 가능성과 후속 피드백

후보, 정리안, 승인, 활성화, 취소, 검증, 실패, 보류를 durable run으로 조회한다. 반복 잡음의 유입 경로는 기록할 수 있지만, ingest 정책 변경은 후속 출시의 별도 승인 대상이다.

### 3.2 비목표

- Reconciler가 기존 memory 본문·상태·metadata·relation·anchor를 수정하는 것
- observation·session·pin 자체를 정리하거나 수명주기를 바꾸는 것
- LLM이 SQL 또는 filesystem을 직접 조작하는 것
- 전체 프로젝트를 하나의 정리 본문으로 압축하는 것
- 영구 삭제, 무제한 전역 정리, cross-project 정리
- similarity나 LLM confidence만으로 자동 활성화하는 것
- 모순을 근거 없이 해소하거나 사용자 정책을 자동 생성하는 것
- 검색 요청마다 LLM을 호출해 정리하는 것
- 첫 출시에서 ingest 정책을 자동 변경하거나 분산 hub 정리를 구현하는 것

---

## 4. 핵심 원칙

### 4.1 LLM은 판단하고 시스템은 활성화 권한을 통제한다

```text
candidate detector → LLM judge → policy gate → activation executor → validator
```

LLM은 관계와 대표를 판단하고 정리 본문을 제안한다. 원본 수정, SQL, filesystem, 외부 URL 실행, index 직접 수정 권한을 갖지 않는다.

### 4.2 생성·승인·활성화를 분리한다

정리 본문 생성은 적용이 아니다. 생성된 결과는 비활성 상태로 저장하고 원본 일치, 정책, 구조·index 검증을 통과한 뒤 활성화한다. `MERGE`·`SUPERSEDE`는 live run에서 category와 관계없이 자동 활성화한다. 명시적으로 보호한 원본은 LLM 판단 후보에서 제외한다. dry-run은 preview와 판단 이력을 저장하지만 검색·context·Overview의 유효 결과를 바꾸지 않는다.

### 4.3 보류와 no-op을 정상 결과로 취급한다

증거가 부족하면 needs_review로 남긴다. 조건이 다른 원본을 억지로 묶거나, 실행마다 본문을 새로 만드는 것을 요구하지 않는다.

### 4.4 원본과 관계를 보존한다

정리의 supersede, archive, stale 표시는 파생 결과에서만 표현한다. 원본의 상태나 관계를 바꾸지 않는다. 새 관계도 별도 정리 계층에 저장한다. 기존 relation type과 신규 요구의 매핑은 구현 설계에서 확정한다.

### 4.5 국소 정리와 원본 scope를 유지한다

한 project 안에서 topic, anchor, 출처, 시점을 기준으로 후보를 좁힌다. 정리 결과와 Overview가 원본의 접근 범위를 넓혀서는 안 된다.

### 4.6 수집 정책 개선은 후속 단계다

반복 잡음의 출처를 기록하되, 첫 출시에서 hook이나 ingest 정책을 바꾸지 않는다.

### 4.7 저장 계층과 읽기 결과를 구분한다

- canonical store: 기존 memory와 observation·session·pin·relation·anchor 원본
- curated results: 대표 참조, 새 정리 본문, claim별 근거, 파생 관계, 활성화·유효성 정보
- curation ledger: run, snapshot, candidate, proposal, receipt, validation 이력
- effective read model: 활성 정리 결과와 정리되지 않은 원본으로 구성한 검색·context 읽기 모델
- Project Overview: 활성 정리 결과를 종합한 프로젝트 단위 파생 결과

정리 본문은 검색에 사용하는 파생 지식이며, 원본을 덮어쓰는 두 번째 정본이 아니다. 원본 복제 금지 원칙은 근거가 연결된 새 정리 본문의 저장을 금지하지 않는다.

---

## 5. 용어 정의

- Memory: 기존 mem-mesh 저장소에 있는 장기 지식 원본.
- Observation / Session / Pin: 첫 출시에서는 읽기 전용 판단 근거로 참조하는 기록.
- Provenance: 원본의 생성 경로와 정리 본문의 claim을 원본으로 추적하는 정보.
- Anchor: commit, file path, file hash 등 원본이 참조하는 코드 상태.
- Candidate group: 같은 지식일 가능성이 있어 함께 검토할 project 내 원본 묶음.
- Representative memory: 묶음에 속한 기존 원본 중 선택한 기준점. 프로젝트 전체의 단일 대표가 아니다.
- Curated result: 대표 참조, 원본 목록, 새 정리 본문, 근거와 유효성을 갖는 파생 결과.
- Proposal: 정리 결과와 그 활성화를 제안하는 비활성 검토 대상.
- Effective read model: 활성 정리 결과와 아직 정리하지 않은 원본을 결합한 읽기 모델.
- Reconcile run: 고정된 입력 snapshot과 정책으로 수행한 정리 작업.
- Curation ledger: 판단·승인·활성화·취소·검증 이력.
- Receipt: 실제 활성화·취소와 검증 결과를 연결한 기록.
- Supersede: 파생 읽기 모델에서 구버전보다 새 근거를 우선하는 관계. 원본 상태는 바꾸지 않는다.
- Archive: 원본을 유지한 채 승인된 파생 정책으로 기본 검색·context에서 제외하는 처리.
- Rollback: 정리 결과의 활성화를 취소하는 처리. 원본 내용을 복구하는 작업이 아니다.
- No-op: 유효 읽기 결과를 바꿀 안전한 제안이 없는 정상 결과.
- Project Overview: 여러 활성 정리 결과를 종합한 프로젝트 설명.
- Evolution Loop: 후속 출시에서 정리와 수집 정책의 개선을 연결하는 반복 구조.

---

## 6. 사용자와 시스템 주체

### 6.1 자동화 시스템

비동기로 후보를 판정한다. dry-run에서는 preview를 저장하고, activation-capable run에서는 검증된 `MERGE`·`SUPERSEDE` 결과를 자동 활성화한다. 명시적 보호 대상은 후보에서 제외하고 `NEEDS_REVIEW`는 활성화하지 않는다.

### 6.2 Coding agent

검색·context에서 유효 정리 결과와 원본 참조를 받는다. 원본 조회, 정리 실행, 제안 조회를 요청할 수 있지만 승인 권한을 우회하지 않는다.

### 6.3 프로젝트 운영자

정리 본문과 대체 판단을 승인하거나 거부한다. 적용 취소, 자동 적용 정책, 실패 run과 Overview의 검토 범위를 확인한다.

### 6.4 LLM judge

읽기 전용 evidence에서 관계·대표·정리 본문을 제안한다. 활성화 권한과 원본 mutation 권한을 갖지 않는다.

### 6.5 Activation executor

정책과 원본 precondition을 다시 검사하고, 파생 결과의 활성화·취소와 receipt를 transaction으로 기록한다.

### 6.6 Validator

원본 불변, 파생 index, 근거, 읽기 일관성, Overview 의존성과 재실행 안전성을 검증한다.

---

## 7. 사용자 시나리오

### 7.1 반복된 memory의 대표 선택과 새 정리 본문

같은 project에 비슷한 결론 8개가 있다.

1. detector는 동일 지식 후보를 묶고 조건이 다른 원본은 구분한다.
2. LLM은 반복 기록, 새 측정, 별도 조건을 구별한다.
3. 묶음 내 기존 원본 중 대표를 선택한다.
4. 여러 원본의 고유 사실·조건·예외를 모아 새 정리 본문을 제안한다.
5. 시스템은 claim별 원본 근거와 입력 일치를 검증한 뒤 결과를 활성화한다.
6. 검색·context는 활성 정리 본문을 반환하고 같은 묶음의 원본 중복 노출을 접는다.
7. 원본 8개는 그대로 조회할 수 있다.

### 7.2 자동 생성 잡음의 검색 제외

동일한 내부 summary가 반복 저장된다. 출처가 확인되면 검색 제외 제안을 만든다. 기본은 승인 후 활성화다. 프로젝트별 자동 적용을 명시한 낮은 위험 사례만 자동 활성화한다. 출처가 불명확하면 needs_review로 남긴다. 원본이나 hook은 바꾸지 않는다.

### 7.3 원본 또는 anchor 변경

원본 본문·metadata·관계·anchor 등 판단 입력이 바뀌면 기존 결과의 유효성을 다시 검사한다. 불일치한 결과는 stale로 표시하고 유효 읽기 모델에서 제외한다. 영향받은 Overview도 stale로 표시한다. 새 snapshot에서 재판정하고 원본 자체는 수정하지 않는다.

### 7.4 모순과 조건 차이 보존

두 원본의 결론이 달라도 시점과 측정 조건이 다르면 하나로 단정하지 않는다. 조건을 구분한 정리 본문이나 파생 관계를 제안하고, 증거가 부족하면 보류한다. 실제 모순을 대표 선택만으로 숨기지 않는다.

### 7.5 Project Overview 통합

활성화된 SQLite 규칙, MCP 버전 관리, 장애 경과 등 묶음별 정리 결과를 종합한다. 기존 Overview 화면에서 프로젝트 설명·주요 결정·최근 변경·미해결 문제와 원본 근거를 제공한다. 정리하지 않은 memory가 있으면 범위와 미검토 여부를 표시한다. 단순히 오래됐다는 이유로 유효한 중요 결정을 제외하지 않는다.

---

## 8. 전체 아키텍처

```text
Canonical store: memories / observations / sessions / pins / relations / anchors
  │ read-only snapshot
  ▼
Candidate detector → Evidence bundle → LLM judge
                                      │ 대표 + 관계 + 새 정리 본문
                                      ▼
                              비활성 제안 / curation ledger
                                      │ 정책 검사 + 필요 시 승인
                                      ▼
                              검증된 정리 결과 활성화
                                      │
                ┌─────────────────────┴───────────────────┐
                ▼                                         ▼
Effective read model                            Project Overview 종합
활성 정리 결과 + 미정리 원본                      활성 정리 결과와 원본 근거
                │                                         │
                ▼                                         ▼
          검색 / context                            기존 Overview 화면
```

### 8.1 Canonical store

기존 memory 모델과 원본 정본을 유지한다. Reconciler를 위해 원본을 이관하거나 원본 행에 visibility, reconcile revision, stale 상태를 쓰지 않는다. 기존 내용·metadata·관계·anchor의 버전 또는 hash를 읽어 precondition을 구성한다. 원본 불변은 Reconciler의 권한 제약이며, 기존 사용자의 일반 수정 기능을 금지하는 뜻은 아니다.

### 8.2 Curated results와 curation ledger

첫 출시는 기존 SQLite DB 안의 별도 테이블을 사용한다. 실제 테이블 이름과 migration은 구현 설계에서 확정한다. DB 작업은 기존 async Database 계층을 따른다.

정리 결과에는 project, 묶음, 원본 ID와 입력 버전, 대표 ID, 새 정리 본문, claim별 evidence, 파생 관계, 활성화·유효성 정보를 저장한다. 감사 ledger에는 run, snapshot, 제안, receipt, 검증, 필요한 승인과 취소 이력을 저장한다. 원본 전문을 별도 정본으로 복제하지 않는다. evidence excerpt는 제한·redaction하고, 새 정리 본문에도 같은 민감정보 정책을 적용한다.

### 8.3 Effective read model

검색·context는 동일한 활성 결과 집합을 사용한다. 정리된 묶음에서는 정리 본문을 반환하고 대표와 원본 참조를 제공한다. 묶음에 포함되지 않은 원본은 기존 scope 안에서 검색 대상에 남는다. 활성화된 잡음 제외 결과만 기본 읽기에서 숨긴다.

후보를 raw top-k에서 얻은 뒤 중복만 제거해 결과 개수가 줄어드는 방식으로 끝내지 않는다. 파생 본문도 검색 대상으로 평가하고 scope와 요청 개수를 유지하는 읽기 전략을 구현 설계에서 정한다. 원본 FTS/vector를 정리 결과로 덮어쓰지 않는다. 파생 검색 index도 기존 SQLite·sqlite-vec·sentence-transformers 제약을 따른다.

원본 직접 조회와 원본 기준 검색을 제공한다. 비활성 결과, stale 결과, 취소된 결과를 유효 읽기 모델에 섞지 않는다. 동일 원본을 포함하는 결과가 충돌하면 자동으로 둘 다 활성화하지 않고 보류하거나 기존 활성 결과의 명시적 교체를 요구한다.

### 8.4 Project Overview

기존 Overview 화면을 유지하고 생성 기반을 활성화된 유효 정리 결과로 교체한다. 묶음별 본문을 프로젝트 단위로 종합하는 단계를 둔다. 최근 원본 20개만으로 프로젝트 전체를 대표했다고 간주하지 않는다.

Overview는 입력 정리 결과의 ID·revision, 원본 근거, 생성 시점, 포함 범위, 미검토 memory 여부와 stale 상태를 가진다. 정리 결과의 활성화·취소·무효화 또는 미검토 원본 증가를 반영해 갱신 필요 여부를 표시한다. 활성 결과가 없으면 정리 결과 부재를 표시하고 임의로 원본 요약 생성 경로로 전환하지 않는다. 미검토 범위를 포함한 부분 Overview는 그 범위를 명시한다.

정리 범위는 현재 canonical 원본 수와 유효한 활성 정리 결과가 인용한 고유 원본 수로 표시한다. 인용되지 않은 원본이나 미검토 제안이 있으면 부분 Overview로 표시한다. 새 미정리 원본 또는 제안 상태가 바뀌면 저장된 Overview를 갱신 필요 상태로 표시한다.

### 8.5 기존 LLM 경로 재사용

기존 shared Chat LLM 설정, Reconcile 전용 설정과 provider 구현을 재사용한다. 묶음 판정·정리 본문은 기존 Reconcile 설정 경로를, Overview 종합은 기존 Chat LLM 설정 경로를 활용한다. 두 단계의 입력은 활성화 상태와 원본 참조를 공유한다. 별도 provider 체계나 암묵적 fallback chain을 추가하지 않는다. 실제 provider·model·prompt version은 각 결과에 기록한다.

### 8.6 기존 Reconcile과의 경계

현재 pair 기반 Reconcile, Curation 승인, Overview 구현을 재사용 가능한 기반으로 검토하되 동작이 이미 이 PRD를 충족한다고 간주하지 않는다. 기존 원본을 deprecated로 바꾸는 승인 경로는 새 Reconciler의 적용 경로로 사용하지 않는다. 레거시 제안·기능의 전환 및 호환성은 구현 설계에서 정하고, 이 문서 수정으로 기존 동작을 변경하지 않는다.

생성 시점 차이가 3일 미만인 쌍을 제외하는 기존 역전 탐지 조건을 중복 정리에 그대로 적용하지 않는다. 같은 날 생긴 중복도 정리 후보가 될 수 있어야 한다.

---

## 9. Reconcile run lifecycle

### 9.1 상태

```text
created
  → queued
  → detecting
  → judging
  → proposing
  → policy_checking
  → applying
  → validating
  → completed
```

예외 상태:

```text
paused
retryable
cancel_requested
cancelled
failed
partial_success
needs_approval
```

### 9.2 상태 의미

| 상태 | 의미 |
|---|---|
| `created` | 실행 요청만 생성된 상태 |
| `queued` | 감지 작업이 worker를 기다리는 상태 |
| `retryable` | 감지 대기열이 가득 차서 영속 기록으로 대기하는 상태 |
| `detecting` | 원본 snapshot을 고정하고 후보를 수집·그룹화하는 중 |
| `judging` | LLM이 evidence bundle을 판정하는 중 |
| `proposing` | 구조화된 proposal을 저장하는 중 |
| `policy_checking` | 자동 적용 가능성을 평가하는 중 |
| `needs_approval` | 사용자 또는 운영자 승인이 필요한 proposal이 있음 |
| `applying` | 검증된 파생 결과를 활성화하는 중 |
| `validating` | 구조·검색·의미 검증을 실행하는 중 |
| `completed` | 모든 대상이 적용, 보류 또는 no-op으로 종결됨 |
| `partial_success` | 일부 proposal은 적용됐고 일부는 실패·보류됨 |
| `failed` | run 자체가 정상적으로 결과를 내지 못함 |
| `cancelled` | 사용자가 취소했거나 정책상 중단됨 |

Run 상세의 `candidate_counts`를 주기적으로 조회해 전체, 대기, 처리, 판정 완료, 보류, 실패 수와 진행률을 표시한다. `decided`는 전체 후보 수에서 `pending_judgment`와 `processing`을 뺀 값이며 preview, hold, 실패, 자동 활성화 결과를 포함한다. 후보가 없는 terminal run은 진행률 100%로 표시한다.

`queued`와 `retryable` run은 후보 수를 0으로 표시한다. Worker가 `detecting`으로 전환할 때 원본 snapshot을 고정한다. 실행 시각부터의 판단 budget은 감지가 끝난 시점에 시작한다.

활성화 전 구조·근거·index 검증은 policy gate와 적용 준비 과정에서 수행한다. lifecycle의 validating 단계는 실제 활성화와 receipt, 읽기 결과를 확인하는 최종 검증이며 사전 검증을 대신하지 않는다.

### 9.3 완료 조건

run은 모든 candidate가 다음 중 하나가 되었을 때 종결할 수 있다.

- applied
- skipped with reason
- needs_review
- failed with retryability
- not_a_candidate

단순히 LLM 응답을 받은 것만으로 completed가 되지 않는다. proposal 저장, policy 결과, 적용 또는 보류 사유, validation 결과가 있어야 한다.

---

## 10. Candidate Detection

Candidate Detection은 의미 판단이 아니라 LLM 입력 범위를 줄이는 단계다. detector는 낮은 비용의 규칙과 검색을 사용한다.

### 10.1 후보 생성 신호

#### A. 내용 유사성

- embedding similarity
- FTS lexical overlap
- normalized title 또는 summary overlap
- 핵심 entity와 action의 overlap

#### B. provenance 유사성

- 같은 session
- 같은 observation batch
- 같은 agent/event/call type
- 같은 source document
- 같은 hook event

#### C. 시간 관계

- 짧은 기간 안의 반복 기록
- 같은 결론에 대한 최신 업데이트
- 특정 incident 전후의 memory

#### D. anchor 관계

- 같은 repository
- 같은 file path prefix
- 같은 commit 또는 branch
- 동일 파일의 이전 hash와 현재 hash

#### E. graph 관계

- 이미 `related`, `references`, `depends_on` 관계가 있는 memory
- 고립된 memory
- 동일 target을 가리키는 여러 relation
- supersede chain 후보

#### F. 품질 신호

- unknown agent
- 비정상적으로 짧거나 긴 내용
- 내부 prompt 또는 tool transcript 패턴
- 동일한 템플릿 반복
- session-local 작업 지시가 permanent memory에 저장된 패턴

#### G. 검색 사용 신호

- 장기간 참조되지 않은 자동 생성 memory
- 자주 검색되지만 결과에 계속 중복 노출되는 memory
- 동일 query에서 항상 함께 반환되는 memory

### 10.2 후보 그룹화

한 candidate group은 다음 범위 중 하나를 넘지 않아야 한다.

- 하나의 project
- 하나의 tenant/user scope. 첫 출시에는 cross-project 예외를 두지 않는다.
- 최대 `N`개의 memory
- 최대 `M`개의 provenance source
- 최대 `T`일의 temporal window

후보가 범위를 넘으면 여러 group으로 분할한다. group 전체를 LLM에 넣을 수 없으면 대표 memory와 주변 evidence를 계층적으로 선택한다.

현재 detector의 임시 상한은 `N=12`, `M=8`, `T=365`다. 실행 budget에 상한을 기록한다. 최종 기본값은 실제 데이터 baseline으로 확정한다.

`candidate-v5`는 메모리마다 최근 후보 그룹을 최대 256개 비교한다. 프로젝트 관계는 한 번에 조회하며, 비교 한도를 실행 통계에 기록한다. 이 한도 밖의 유사 메모리는 별도 그룹으로 남을 수 있다.

시간 범위는 그룹 전체의 가장 이른 생성 시각과 가장 늦은 생성 시각으로 계산한다. timezone을 UTC로 정규화하고 timezone 없는 기존 시각은 UTC로 해석한다. 상한을 넘으면 anchor·유사도·관계 신호가 있어도 분할한다. 생성 시각을 해석할 수 없으면 감지를 실패 처리하고 사유를 표시한다.

잡음 판정은 단일 원본도 후보가 될 수 있다. 대표 선택과 새 정리 본문은 지식 묶음에 적용하며, 잡음 제외나 보류 후보에 강제하지 않는다.

### 10.3 후보 생성 결과

아래 JSON은 논리 예시이며 확정된 public schema가 아니다.

```json
{
  "candidate_group_id": "cg_01J...",
  "scope": {
    "project_id": "term-mesh",
    "anchor_prefix": "Sources/Parallel/",
    "time_start": "2026-10-01T00:00:00Z",
    "time_end": "2026-10-19T00:00:00Z"
  },
  "memory_ids": ["mem_a", "mem_b", "mem_c"],
  "signals": [
    {"kind": "embedding_similarity", "score": 0.91},
    {"kind": "same_anchor", "score": 1.0},
    {"kind": "same_project", "score": 1.0}
  ],
  "detector_version": "candidate-v1",
  "status": "pending_judgment"
}
```

---

## 11. Evidence Bundle

LLM은 memory 본문만 받아서는 안 된다. 각 candidate group에 대해 다음 정보를 포함하는 Evidence Bundle을 만든다.

### 11.1 필수 입력

- memory ID
- memory 본문
- category
- title 또는 abstract
- created_at, updated_at
- project_id
- origin
- client 또는 producer
- session/pin provenance
- typed relations
- anchor commit, branch, file paths, file hashes
- 원본 상태와 별도 정리 결과의 활성화·stale·supersede 상태
- 해당 memory가 참조된 검색·context 통계
- candidate를 만든 detector signal

필수 입력의 원본 metadata가 없으면 부재를 명시한다. 출처나 anchor를 추측해 채우지 않고, 필요한 근거가 없으면 보류한다.

### 11.2 선택 입력

- 관련 observation 원문 또는 redacted excerpt
- 같은 session의 요약
- 근처 memory와 relation neighborhood
- 현재 파일의 짧은 코드 excerpt
- 최근 업데이트된 유사 memory
- 이전 reconciliation proposal과 receipt
- 사용자 승인 또는 거부 이력

### 11.3 Evidence Bundle 원칙

- 후보와 직접 관련 없는 전체 project 데이터를 넣지 않는다.
- 민감한 credential, token, password, 전체 transcript는 기본적으로 제외한다.
- 원문을 보낼 필요가 없으면 hash와 metadata만 보낸다.
- LLM이 근거 없이 결론을 만들지 않도록 각 claim의 source reference를 표시한다.
- 서로 다른 시점의 기록을 현재 사실로 평탄화하지 않는다.

### 11.4 Bundle 예시

```json
{
  "candidate_group_id": "cg_01J...",
  "memories": [
    {
      "id": "mem_old",
      "content": "병렬 실행은 coordination 비용 때문에 단일 실행보다 느리다.",
      "category": "decision",
      "created_at": "2026-08-01T10:00:00Z",
      "project_id": "term-mesh",
      "origin": "session",
      "anchors": {
        "commit_hash": "abc123",
        "file_paths": ["Sources/Leader/Policy.swift"]
      }
    },
    {
      "id": "mem_new",
      "content": "병렬 실행의 지연은 coordination보다 worker wait가 지배한다.",
      "category": "decision",
      "created_at": "2026-10-07T10:00:00Z",
      "project_id": "term-mesh",
      "origin": "user",
      "anchors": {
        "commit_hash": "def456",
        "file_paths": ["Sources/Leader/Policy.swift", "Benchmarks/parallel.md"]
      }
    }
  ],
  "relations": [],
  "detector_signals": ["same_project", "same_anchor_prefix", "semantic_similarity"],
  "required_output": "reconcile_decision_v1"
}
```

---

## 12. LLM Judge 계약

### 12.1 판단 범위

- 원본들이 같은 지식인지, 별도 조건이나 실제 모순인지 구분한다.
- 같은 지식의 묶음에서 대표 원본을 선택한다.
- 여러 원본의 필요한 사실·시점·조건·예외를 모아 새 정리 본문을 제안한다.
- 보존한 claim과 제거한 반복 표현, 각 claim의 원본 근거를 제시한다.
- 부족한 증거와 검토 필요 사유를 기록한다.

대표는 반드시 입력 묶음에 존재하는 원본 ID다. 정리 본문 생성은 원본 변경이나 승인 없이 활성화할 권한을 주지 않는다. 조건이 다른 후보는 분리하거나 보류할 수 있다.

### 12.2 논리 action

`keep`, `merge`, `supersede`, `archive`, `add_relation`, `mark_stale`, `quarantine`, `needs_review`, `no_op`을 의미 판단의 논리 action으로 사용한다. 실제 public schema와 기존 verdict 매핑은 구현 설계에서 확정한다.

- merge: 여러 원본에서 새 파생 본문을 생성한다. 원본 행을 합치거나 삭제하지 않는다.
- supersede: 파생 읽기 모델에서 유효한 최신 근거를 우선한다. 원본 status는 바꾸지 않는다.
- archive / quarantine: 승인된 파생 정책으로 기본 검색·context에서 제외한다. 원본은 조회 가능하다.
- add_relation / mark_stale: 정리 계층에 관계·유효성 판단을 기록한다. 원본 relation·anchor는 수정하지 않는다.

### 12.3 논리 출력 요구

candidate 식별자, 입력 원본 ID와 버전/hash, 대표 원본 ID, action, 정리 본문, claim별 evidence 참조, 보존한 조건·예외, 제거한 반복 표현, 이유, 불확실성, confidence와 risk를 포함한다. 검토자는 confidence만으로 승인을 대신하지 않는다.

이 목록은 제품 계약이다. 정확한 JSON 필드명과 API signature는 기존 Pydantic·MCP schema 관례를 확인한 뒤 확정한다.

### 12.4 새 정리 본문의 추가 조건

원본 근거 없는 사실을 추가하지 않는다. 최신 원본이라는 이유만으로 정답으로 간주하지 않는다. 시점과 조건을 보존하고, 실제 모순은 드러내거나 검토로 보낸다. 대표 하나만으로 모든 사실을 설명했다고 가정하지 않는다. 새 정리 본문과 그 대표 참조를 함께 저장하고 정책·검증 전에는 비활성으로 둔다.

### 12.5 실패 처리

- JSON/schema 실패: 보정 재시도 1회 후 실패로 기록한다.
- timeout/provider 실패: 제한된 재시도와 실패 이력을 남긴다. 활성 읽기 결과는 유지한다.
- 입력에 없는 ID, 근거 없는 claim, 누락된 필수 evidence, 불허 action: 제안을 거부한다.
- payload 한도 초과: evidence를 조용히 잘라 판정하지 않고 분할하거나 보류 사유를 기록한다.
- 반복 실패: 해당 후보를 검토 대상으로 남기고 run은 실제 처리 결과에 맞게 종결한다.

### 12.6 모델 정책

기존 LLM resolver와 provider를 재사용한다. model과 prompt version을 기록하고 이미 저장한 정리안을 재조회할 수 있게 한다. 모델을 다시 호출해 동일 문장이 나온다고 재현성을 보장하지 않는다. LLM 미설정이나 장애가 원본 저장·검색을 막지 않으며, 의미 판정을 결정적 규칙으로 조용히 대체하지 않는다.

---

## 13. 위험과 자동 적용 정책

### 13.1 기본 정책

dry-run을 기본으로 한다. activation-capable run에서는 현재 canonical인 `MERGE`·`SUPERSEDE` 결과를 category와 관계없이 자동 활성화한다. 명시적 보호 대상은 후보에서 제외하고 `NEEDS_REVIEW`는 hold로 유지한다. noise suppression과 파생 관계 추가는 기존 프로젝트 정책을 따른다. Overview는 활성화된 결과만 종합하고 preview나 hold 제안을 근거로 사용하지 않는다.

### 13.2 자동 허용 범위

- 현재 canonical인 입력의 검증된 `MERGE`·`SUPERSEDE` 결과
- 출처가 확인된 자동 생성 잡음의 기본 검색·context 제외
- 원본을 바꾸지 않는 낮은 위험의 파생 관계 추가

`MERGE`·`SUPERSEDE` 자동 활성화에는 canonical source, 명시적 보호 대상 제외, 일치하는 precondition, 허용 budget, provenance·index 검증 통과가 필요하다. 기존 noise suppression과 relation 추가 정책은 같은 project, 확인된 provenance, 보호 범주 제외, 일치하는 precondition, 적용 budget, 검증 통과를 요구한다. confidence는 이 검사를 대신하지 않는다.

### 13.3 승인 필요 또는 금지 조건

- 현재 canonical이 아닌 입력 또는 사용자 작성 여부가 불명확한 입력: 활성화 보류와 재검토 필요
- `NEEDS_REVIEW`: hold로 두며 승인·활성화 금지
- 모순, 조건 불명확, 유일 근거 손실 가능성, stale 입력: 보류 또는 재판정
- cross-project 정리, 원본 수정·삭제, provenance 손실: 첫 출시에서 금지

보안·아키텍처는 보호 정책의 의미 범주이며, 기존 memory category enum에 같은 항목이 있다고 가정하지 않는다.

---

## 14. Policy Gate

### 14.1 Scope와 provenance

project를 명시하고 원본 접근 권한, anchor·출처 범위를 유지한다. 대표와 모든 evidence ID가 후보 입력에 있는지 확인한다. 정리 본문의 claim을 해당 원본 버전으로 추적할 수 없으면 활성화하지 않는다.

### 14.2 입력 유효성

판정 직전과 활성화 직전에 원본의 내용·관련 metadata·관계·anchor 입력이 snapshot과 같은지 확인한다. 다르면 제안을 stale로 표시하고 재판정한다. 활성 결과의 입력이 바뀌면 이를 무효화하고 의존 Overview를 stale로 표시한다. 일반 사용자 수정은 허용하되 Reconciler가 그 변경을 덮어쓰지 않는다.

실행은 시작 시점의 유효 정책과 hash를 보존한다. 각 LLM 호출과 활성화 직전에 현재 정책을 비교한다. 정책이 달라지면 남은 판정과 활성화를 보류하고 새 실행을 요구한다. 활성화 transaction 안에서도 정책을 다시 확인한다.

### 14.3 적용 budget

후보 수, LLM 호출 수, 활성화 수, 실행 시간과 비용에 한도를 둔다. 한도에 도달하면 다음 proposal의 처리를 중단하고 미처리 사유를 기록한다. 이미 완료한 활성화는 receipt로 유지한다. proposal 한 건은 부분 활성화하지 않는다. 실제 기본 수치는 baseline 이후 확정한다.

활성화 한도는 실행 시작 시 저장한 `budget.max_activations`로 고정한다. 성공한 activation receipt의 누적 수로 사용량을 계산하고 transaction 안에서 다시 확인한다. 취소·stale 전환은 이미 쓴 한도를 복원하지 않는다. 실패하여 rollback한 활성화와 `index_repair`는 사용량에 넣지 않는다. 이미 적용한 제안의 반복 요청도 새 사용량을 만들지 않는다.

활성화 한도 초과는 보류 사유로 남기고 자동 재시도하지 않는다. 저장된 한도가 없거나 잘못됐으면 현재 전역 기본값으로 대체하지 않고 새 실행을 요구한다. 한도가 0이면 활성화하지 않는다.

제안을 만들었어도 한도 때문에 활성화하지 못한 항목이 있으면 run을 부분 성공으로 표시한다. 이미 적용한 결과와 보류 사유를 함께 보존한다.

### 14.4 멱등성과 동시성

판정 중복 방지에는 정렬된 원본 ID·입력 버전/hash, project 범위, detector·policy·prompt/model 버전과 dry-run 여부를 사용한다. Preview와 활성화 가능 실행은 별개로 판정한다. 매번 달라지는 run ID나 LLM 출력 hash만으로 같은 입력을 다른 작업으로 취급하지 않는다. 실제 키의 wire shape는 구현 설계에서 확정한다.

적용에는 저장된 proposal 식별자를 기준으로 한 idempotency 제약을 둔다. 같은 proposal을 반복 승인·적용해도 같은 활성 결과와 receipt를 참조하고 중복 index 항목을 만들지 않는다. 동시 worker가 동일 원본을 포함하는 상충 결과를 함께 활성화하지 못하도록 transaction 안에서 충돌을 확인한다.

### 14.5 승인 취소

취소는 정리 결과의 활성화만 해제한다. 원본과 감사 이력을 삭제하지 않는다. 여전히 유효한 다른 결과와 미정리 원본으로 읽기 모델을 구성하고, 취소 결과에 의존한 Overview를 stale로 표시한다.

Curation의 활성 결과 카드에서 `Deactivate derived result`를 제공한다. 현재 result revision으로 취소를 요청하고 충돌 사유를 표시한다. 성공 후 목록을 갱신하고 의존 Overview의 재생성을 안내한다.

---

## 15. 정리 결과의 적용 인터페이스

### 15.1 제품 계약

- 비활성 정리 결과와 원본 근거를 저장한다.
- 수동 승인이 필요한 파생 정책 제안을 승인·거부하고 활성화 결과를 취소한다.
- 활성화 결과를 취소하고 기존 이력을 조회한다.
- 원본 변경 시 결과를 무효화하고 재검토 대상으로 표시한다.
- 정리 계층에 관계와 검색 제외 정책을 기록한다.
- 읽기 모델과 Overview의 유효성·갱신 상태를 조회한다.

이 인터페이스는 원본 archive, restore, version 생성 또는 relation 수정 API가 아니다. 정확한 API 이름·필드·권한 매핑은 구현 설계에서 확정한다.

### 15.2 공통 조건

run과 proposal 참조, actor, policy version, 입력 precondition, 승인 이력, idempotency 제약을 기록한다. 파생 결과의 활성화 상태와 receipt를 transaction으로 연결한다. 원본 canonical store를 수정하는 경로를 호출하지 않는다.

### 15.3 새 정리 본문의 활성화

1. 원본을 읽고 대표 참조·종합 본문·claim 근거를 비활성 결과로 저장한다.
2. 정책과 활성화 직전 precondition을 확인한다.
3. 파생 검색 index를 준비하고 scope·근거·구조를 검증한다.
4. 검증된 결과만 유효 읽기 모델에 공개하고 receipt를 남긴다.
5. 실패하면 원본과 기존 유효 읽기 결과를 유지하고 실패를 기록한다.
6. 활성화 이후 의존 Overview를 갱신 필요 상태로 표시한다.

본문 생성이나 embedding 실패 때문에 원본을 먼저 비활성화해서는 안 된다. 활성화 공개 경계와 index 준비 방식은 기존 Database transaction 제약을 확인한 뒤 구현 설계에서 확정한다.

---

## 16. 정리 결과와 Curation Ledger 데이터 모델

아래는 논리 데이터 요구다. 실제 테이블 이름·열·JSON 구조·migration은 구현 설계에서 확정한다. 첫 출시는 기존 SQLite DB 안의 별도 테이블을 사용하며 원본 행은 변경하지 않는다.

### 16.1 Run

project와 범위, trigger, lifecycle, detector·policy·prompt/model 버전, snapshot, budget, 통계, 시작·종료 시각과 오류를 저장한다.

### 16.2 Snapshot

입력 원본 ID와 내용·관련 metadata·관계·anchor의 버전/hash, capture 시점, scope와 evidence manifest를 저장한다. 재현용 원문 excerpt는 제한·redaction한다. 원본 전문의 별도 정본을 만들지 않는다.

### 16.3 Candidate

run, 후보 묶음, 원본 목록, detector 신호, evidence manifest, 처리 상태와 실패·보류 사유를 저장한다.

### 16.4 Proposal

candidate, 제안 action, 대표 참조, 원본 입력 버전, 새 정리 본문, claim별 evidence, 이유·불확실성, confidence·risk, precondition, 정책 결과, 검토자·승인·거부 이력과 적용 식별자를 저장한다. 활성화 전에는 유효 읽기 모델에서 제외한다.

### 16.5 Curated result

project, 묶음, 대표 원본 ID, 원본 ID와 입력 버전/hash, 종합 본문, claim별 근거, 파생 관계·검색 제외 판단, 결과 revision, 승인 참조, 활성화와 유효성 상태를 저장한다. 한 묶음의 대표는 원본 하나이며, 정리 본문은 여러 원본을 참조할 수 있다. 동일 원본에 대한 충돌한 활성 결과를 허용하지 않는다.

### 16.6 Receipt와 validation

proposal과 결과 revision, 활성화·취소의 전후 상태, actor, 시점, 검증 결과와 영향받은 읽기 revision을 기록한다. 원본을 수정하지 않았음을 검증할 수 있어야 한다. 취소 이력도 남긴다.

### 16.7 Overview 의존성

프로젝트별 Overview 본문, 입력 정리 결과의 ID·revision, 원본 근거, 생성 시점, model/prompt, 정리 범위·미검토 여부와 stale 상태를 저장한다. 새 본문 생성이 실패해도 이전 결과의 시점과 stale 상태를 확인할 수 있게 한다.

### 16.8 후속 policy feedback

반복 잡음의 pattern, 출처 참조, 권고와 검토 상태를 기록할 수 있다. ingest 정책의 적용과 별도 정책 version 관리는 후속 출시다.

---

## 17. Validation

### 17.1 원본과 구조 검증

- Reconciler 실행·활성화·취소 전후에 기존 memory 본문·상태·metadata·relation·anchor가 바뀌지 않는가
- 대표가 후보 묶음에 속하고 모든 claim의 원본 ID와 입력 버전이 존재하는가
- 비활성 preview와 `NEEDS_REVIEW` hold가 활성화되지 않는가
- canonical `MERGE`·`SUPERSEDE`는 category와 관계없이 검증 뒤 자동 활성화되고 명시적 보호 대상은 후보에서 제외되는가
- 동일 원본을 포함하는 상충 결과가 동시 활성화되지 않는가
- 파생 대체 관계에 cycle이나 고아 참조가 없는가
- 결과·proposal·receipt가 같은 run과 입력을 추적하는가
- 취소 후 원본 조회와 올바른 읽기 대상 구성이 가능한가

### 17.2 Index와 읽기 일관성

원본과 파생 index는 역할이 다르므로 row 수의 단순 일치를 요구하지 않는다. 파생 본문의 embedding과 활성 revision이 일치하고, 검색·context가 같은 활성 결과를 사용하는지 검증한다. 원본 index를 덮어쓰지 않으며, inactive·stale·취소 결과를 유효 검색에 노출하지 않는다. 승인된 잡음 제외와 원본 직접 조회를 구분한다.

### 17.3 의미와 검색 검증

project·anchor scope별 대표 query를 정리 전후 비교한다. expected 원본 ID가 정리 본문의 근거로 남으면 동일 지식의 보존으로 평가할 수 있다. 정리 본문이 검색돼도 핵심 claim·조건·예외와 원본 인용이 빠지면 손실이다. top-k 중복률, unrelated 결과, 반환 개수와 context token을 함께 확인한다. raw top-k에서 중복만 제거해 고유 지식의 recall이 떨어지지 않는지 확인한다.

### 17.4 Replay와 동시 실행

같은 원본 구성·입력 버전·정책의 재실행은 새 중복 결과나 활성화를 만들지 않는다. 같은 proposal의 반복 승인·적용·취소와 두 worker의 동시 처리에서도 중복 상태가 발생하지 않아야 한다. LLM을 재호출해 같은 문장이 나오는 것은 멱등성의 전제가 아니다.

### 17.5 Overview 검증

활성화된 유효 결과만 입력에 포함한다. 핵심 주장의 원본 근거, 범위·미검토 표시, 최신성 표시를 확인한다. 원본 변경과 결과 활성화·취소·무효화가 Overview의 갱신 필요 상태에 반영되는지 확인한다. 프로젝트의 일부만 정리했는데 전체 검토 완료로 표시하지 않는다.

Overview 인용은 현재 정리 입력의 원본 `citations`에 포함된 ID를 허용한다. 같은 project라도 현재 입력에 없는 원본은 허용하지 않는다. 기존 캐시의 정리 결과 ID도 유효 입력에 속할 때만 유지한다. 캐시 dependency는 정리 결과 ID·revision과 원본 hash로 관리한다.

근거가 적으면 짧게 요약한다. 기록된 작업 절차만으로 현재 운영·완료·배포·건강 상태를 추론하지 않는다. 정리 결과 생성 시각을 원본 사건의 발생 시각으로 취급하지 않는다.

---

## 18. Memory Evolution Loop

이 절은 후속 출시의 방향이다. 첫 출시는 반복 패턴을 기록할 수 있지만 hook·ingest 정책을 바꾸지 않는다.

Memory Reconciler가 한 번의 정리 작업이라면 Memory Evolution Loop는 다음 사이클이다.

### 18.1 Loop 단계

```text
Observe
  → Detect recurring pattern
  → Reconcile affected memories
  → Validate result
  → Derive ingestion feedback
  → Apply safe policy change
  → Observe next sessions
  → Measure recurrence
```

### 18.2 재유입 패턴

다음 패턴은 정리만 하지 않고 유입 정책 개선 후보로 만든다.

- 동일한 event type이 반복적으로 permanent memory를 생성
- 특정 client가 provenance 없이 memory 생성
- 같은 prompt template이 내부 summary를 저장
- 특정 agent가 session-local 상태를 decision category로 저장
- anchor가 없는 memory가 특정 project에서 과도하게 생성
- 동일한 low-value content가 여러 session에서 반복

### 18.3 Feedback action

```text
drop
  해당 event를 permanent memory로 승격하지 않음

demote
  memory가 아닌 observation 또는 session ledger로 저장

metadata_only
  원문을 저장하지 않고 event와 hash만 보존

redact
  payload의 특정 필드를 제거한 뒤 저장

route_to_review
  자동 승격 대신 검토 queue로 이동

change_category
  자동 생성 결과를 별도 category로 분리

change_threshold
  promotion에 필요한 confidence 또는 길이 기준 조정
```

### 18.4 Feedback 적용 원칙

- 하나의 run만으로 전역 ingest 정책을 바꾸지 않는다.
- 같은 pattern이 최소 설정된 횟수와 기간 동안 반복되어야 한다.
- 사용자 작성 memory에는 자동 적용하지 않는다.
- policy 변경 자체도 versioned proposal로 기록한다.
- policy 변경 후 recurrence rate가 실제로 감소했는지 측정한다.

---

## 19. 실행 트리거

### 19.1 수동 실행

첫 출시는 project를 지정한 수동 실행을 제공한다. anchor·기간 등으로 범위를 좁히고, dry-run, run·제안 조회, 승인·거부, 활성화·취소와 검증을 수행할 수 있어야 한다. 정확한 CLI 이름과 flags는 구현 설계에서 확정하며 이 문서에서는 실행 가능한 신규 명령을 가정하지 않는다.

운영자는 먼저 해당 project의 dry-run을 시작하고 후보와 판단 결과를 확인한다. 활성화가 필요하면 같은 project에서 activation-capable run을 별도로 시작한다. 워커의 진행 상태와 완료·실패 건수를 확인한다. 검증된 `MERGE`·`SUPERSEDE` 결과는 category와 관계없이 자동 활성화한다. `NO_OP`만 나온 run은 활성 결과를 만들지 않는다. 활성 결과가 생긴 뒤 Project Overview를 생성한다.

### 19.2 예약 실행

예약 reconciliation은 후속 운영 확장으로 둔다. 첫 출시의 Overview 통합에서는 기존 Overview 스케줄과의 호환성과 갱신 필요 상태를 다루되, 새 정리 스케줄러를 필수로 추가하지 않는다.

Project Overview의 예약 갱신은 project별 opt-in이다. 마지막 갱신 뒤 원본이 바뀌거나 활성 정리 결과가 추가되면 다음 허용 간격에 재생성한다. 오래된 원본을 새로 정리한 경우에도 이를 변경으로 취급한다. Reconciler 자체의 예약 실행은 제공하지 않는다.

### 19.3 이벤트 기반 실행

새 원본과 입력 변경은 기존 정리 결과·Overview의 유효성 및 미검토 범위에 반영한다. SessionEnd, anchor 변경, 검색 feedback, 반복 잡음으로 새 reconciliation을 자동 실행하는 정책은 후속 운영 확장이다. 입력 무효화와 자동 재실행은 같은 기능으로 간주하지 않는다.

### 19.4 Hot path 격리

hook과 MCP 검색·저장 hot path는 Reconciler를 기다리지 않는다.

- candidate 생성은 bounded queue에 넣는다.
- LLM 판단은 background worker가 처리한다.
- provider 장애는 memory capture 실패로 전파하지 않는다.
- queue가 가득 차면 정리 작업을 drop하지 않고 retryable 상태로 기록한다.
- 같은 event는 idempotency key로 중복 enqueue를 방지한다.

수동 Web·MCP 실행은 run을 영속 대기열에 기록하고 즉시 반환한다. 감지 대기열은 8개로 제한하며 초과 run은 `retryable`로 남긴다. Worker는 오래된 run부터 처리하고 만료된 감지 lease를 회수한다. 이벤트 기반 자동 실행의 idempotency key는 해당 실행 기능을 추가할 때 적용한다.

---

## 20. API 및 MCP 인터페이스

### 20.1 읽기 기능

run, snapshot 범위, candidate, proposal, curated result, receipt, 검증·유효성 상태를 조회한다. 결과에서 대표 원본과 claim별 근거를 따라갈 수 있어야 한다. 원본 직접 조회와 원본 기준 검색을 제공한다. 기존 Overview 화면은 정리 결과 기반 Overview와 그 범위·시점·stale 상태를 조회한다.

### 20.2 실행 기능

project 범위 정리 시작·취소, 제안 조회, 결과 활성화·취소, 검증, Overview 재생성을 제공한다. 적용은 원본 mutation이 아니라 파생 결과의 활성화다. `MERGE`·`SUPERSEDE`에는 category별 수동 승인을 요구하지 않는다. `NEEDS_REVIEW`는 보류하고 dry-run proposal은 미리보기로 유지한다. 기존 MCP 공통 schema·dispatcher를 따른다.

### 20.3 호환성과 기본값

파생 검색 결과는 MCP의 `minimal`, `compact`, `standard` 압축에서도 전체 `cr_` ID와 `project_id`, `result_kind`, 대표 원본, 원본 인용을 보존한다. Compact context도 primary와 관련 파생 결과의 같은 정보를 유지한다. 원본의 기존 압축 형식은 유지한다.

미정리 원본을 primary로 조회해도, 같은 프로젝트에 활성 파생 결과가 있으면 관련 context는 유효 읽기에서 구성한다. 정리된 원본을 다시 중복 노출하지 않는다. Raw context는 원본을 유지하며, raw와 effective 모두 명시한 project 밖의 primary를 반환하지 않는다.

정확한 endpoint, tool 이름, CLI, 응답 필드와 식별자 형식은 기존 인터페이스를 확인한 뒤 구현 설계에서 확정한다. 기존 검색에서 파생 결과와 원본 인용을 표현하는 방식, 기존 Overview 응답과의 호환성도 그 단계에서 정한다. 이 문서의 논리 모델을 이미 존재하는 API로 간주하지 않는다.

dry-run을 기본으로 한다. 사용자가 activation-capable run을 시작하면, 모든 source가 현재 canonical 상태인 `MERGE`·`SUPERSEDE` 결과를 기존 precondition·provenance·index 검증 뒤 자동 활성화한다. `reconciler_protected` 원본은 후보에서 제외하고 `NEEDS_REVIEW`는 활성화하지 않는다. dry-run은 proposal을 미리보기로 저장하며 승인이나 활성화를 허용하지 않는다. scope 없는 전역 실행을 허용하지 않는다.

---

## 21. 보안과 개인정보

### 21.1 데이터 최소화

LLM에 보내는 데이터는 candidate와 직접 관련된 최소 evidence로 제한한다.

기본 제외:

- credential
- token
- password
- authorization code
- 전체 tool payload
- 전체 transcript
- unrelated project memory
- 사용자가 명시적으로 보호한 memory

Reconciler는 기존 Q/A·speaker turn 판별과 JSON·JSONL의 role/content 및 tool call/result 형식을 검사한다. 지원 형식과 일치하는 본문은 `needs_review`로 보류하고 LLM 호출을 하지 않는다. 해당 형식의 완전한 예제도 보류할 수 있다. 일반 설명 문장이나 관련 단어만으로는 제외하지 않는다.

제외 본문은 새 snapshot에 저장하지 않고 hash·metadata와 제외 사유를 남긴다. 기존 snapshot과 비보관 모드에서 재구성한 근거도 전송 전에 검사한다. 기존 원본과 과거 이력은 삭제하지 않는다. 형식을 바꾼 임의의 transcript를 모두 판별한다고 가정하지 않는다.

기존 두 원본 비교 큐에도 같은 제외 규칙과 redaction을 적용한다. 두 본문의 합이 48,000자를 넘으면 잘라서 판정하지 않고 `dead_letter`와 사유를 기록한다.

### 21.2 전송 정책

- 기존 provider·base URL 설정을 재사용한다. 로컬 또는 외부 사용 가능 범위는 해당 설정과 구현을 따른다.
- Reconciler는 improve·enrich와 같은 공통 LLM 설정을 따른다. 프로젝트별 외부 LLM 허용을 별도로 요구하지 않는다.
- 이전 `allow_external_llm` DB 열은 스키마 호환성을 위해 유지하며, 현재 정책 API와 실행 판단에서는 제외한다.
- dry-run과 live run은 설정된 LLM을 사용한다. 처리·근거 보관 정책이 바뀌면 기존 실행의 남은 후보를 보류하고 새 실행을 요구한다.
- loopback endpoint만 로컬로 분류한다. 그 밖의 endpoint와 기본 provider URL은 외부로 분류해 감사 기록에 남긴다.
- 이 정책은 Reconciler judge와 기존 pair 비교 큐에 적용한다. Project Overview의 Chat LLM 생성 정책은 별도다.
- 외부 전송 전 redaction과 길이 제한을 적용한다.
- provider, model, data classification을 run에 기록한다.
- 실행 시작 시 provider·model·endpoint의 local/external 구분과 `project_memory_evidence` 분류를 저장한다. URL과 인증 값은 저장하지 않는다. 설정이 없으면 `unknown`으로 표시한다.
- 호출 직전 실제 adapter의 provider·model·전송 필드 이름과 redaction 적용 경로를 기록한다. 이 분류는 payload 종류이며 민감 정보가 없다는 판정은 아니다. provider가 실행 설정과 다르면 호출을 보류한다.
- 원문 evidence 저장 금지 모드는 hash와 metadata만 보존한다. 새 정리 본문은 별도 파생 결과로 저장하고 같은 redaction·접근 정책을 적용한다.
- project 정책의 `retain_evidence_content=false`는 새 실행부터 적용한다. 기존 evidence 이력은 삭제하지 않는다.
- 비보관 모드는 본문·제목·anchor·tag와 임의 관계 metadata를 snapshot에 저장하지 않는다. 원본 ID와 hash, 출처 및 제한된 분류 metadata를 보존한다.
- 판정 시 원본 hash를 확인한 뒤 근거를 메모리에서 재구성한다. redaction과 전체 payload 한도를 적용하며, 원본이 바뀌면 LLM 호출을 보류한다.

### 21.3 접근 제어

- project scope에 따라 candidate와 proposal을 제한한다.
- 다른 사용자의 private memory를 cross-project judge input에 섞지 않는다.
- 승인 권한과 실행 권한을 분리할 수 있어야 한다.
- ledger·정리 본문·Overview 조회에도 원본과 같은 접근 정책을 적용한다.

### 21.4 Prompt injection 방어

memory와 observation은 데이터이지 지침이 아니다. LLM judge prompt는 evidence 내부의 지시문을 실행하지 않도록 명시한다.

- memory 본문이 system instruction을 덮어쓰지 않음
- evidence의 외부 URL 지시를 따르지 않음
- tool call을 요청하는 memory를 실행하지 않음
- 판단 결과는 schema validation과 policy gate를 거침

---

## 22. 관측성과 운영

### 22.1 Run metrics

- run 수
- 성공·실패·partial_success 비율
- 평균·p95 실행 시간
- candidate 수
- LLM 호출 수와 token 비용
- proposal action 분포
- 자동 적용 비율
- 승인 대기 시간
- validation 실패율
- replay non-idempotency 비율

각 run에서 감지한 후보 그룹 수와 같은 입력의 선행 후보 때문에 생략한 그룹 수를 별도로 기록한다. 후보가 0개인 재실행은 생략 사유를 표시한다.

Replay 저장 이력 검사는 project별 고유 `input_policy_hash`를 분모로 사용한다. 같은 hash의 파생 결과 또는 activation receipt가 둘 이상이면 비멱등 입력으로 센다. 취소된 결과의 이력도 포함하고 `index_repair`는 activation으로 세지 않는다. 입력이 없으면 비율은 null이다. 중복 결과·활성화의 초과 개수와 이상 알림을 제공한다. 이 검사는 저장 부작용을 측정하며 LLM 출력의 의미적 동일성은 증명하지 않는다.

Provider가 보고한 input·output token과 사용량이 누락된 호출 수를 별도로 기록한다. 금액 환산은 model별 단가를 확인한 뒤 적용한다. 추정 token을 실제 비용으로 표시하지 않는다.

LLM 호출 실패와 응답 검증 실패를 판정 호출 실패로 센다. 재시도 후 성공한 경우에도 실패한 호출 수를 유지한다. Index·활성화 실패는 판정 실패율에 포함하지 않는다.

검증 이력의 실패 이유에 index 또는 embedding 오류가 기록되면 별도 index 검증 실패로 센다. 일반 validation 실패 수와 함께 표시하되 LLM judge 실패로 합산하지 않는다.

### 22.2 Quality metrics

- memory 중복 노출률
- project별 유효 정리 결과와 미정리 원본의 규모
- 검색 제외 또는 정리 결과 활성화의 취소 비율
- contradiction unresolved 수
- stale anchor 해결 시간
- orphan relation 수
- provenance coverage
- 대표 query recall 변화
- top-k 중복률
- context token 절감량
- 사용자 승인 거부율

`NEEDS_REVIEW` 제안은 선택형 `review_reason`을 보존한다. 값은 `contradiction`, `insufficient_evidence`, `scope_mismatch`, `uncertain_provenance`, `other`다. 값이 없는 과거 응답은 미분류로 센다. 자유 문장의 단어로 사유를 추측하지 않는다. 기존 `conflict` 판정은 명시적 모순으로 정규화한다.

미해결 모순 수는 현재 보류 상태이며 `contradiction`으로 분류된 제안 수다. 사유별 보류 수와 미분류 수를 함께 제공한다. 이 값은 전체 원본의 모순 수나 해결률을 뜻하지 않는다. 다른 프로젝트의 사실이나 불확실한 프로젝트 경계는 `scope_mismatch`로 구분한다. 사유 코드가 있어도 승인·활성화는 허용하지 않는다.

2026-10-21 합성 평가에서 `reconciler-v9`와 `kiro/claude-haiku-4.5`는 6개 사례를 통과했다. 같은 조건의 모순과 프로젝트 배정 불일치의 기대 사유도 확인했다. Fixture hash는 `d94a8fec3ae65816278d01fb83698b47da25dbb55726b8fb935bda991d65416e`다. 실제 프로젝트 데이터의 품질 평가는 별도로 필요하다.

활성 claim의 provenance coverage는 원본 참조, 결과의 source 연결, 같은 project의 원본 존재 여부로 계산한다. Orphan relation은 활성 관계의 양 끝 원본이 없거나 project 범위를 벗어난 경우로 센다.

Anchor 해결 시간은 클라이언트가 보고한 `stale → fresh` 상태 전이 사이의 경과 시간이다. 검증 이력에 상태 전이만 기록하고 원본 본문은 바꾸지 않는다. 같은 상태의 반복 보고는 시작 시점을 갱신하거나 새 표본을 만들지 않는다. 상태와 이력은 같은 transaction에 저장한다.

완료 표본 수·평균·p95, 미해결 구간 수와 가장 오래된 경과 시간을 project별로 제공한다. 시작 이력이 없는 과거 stale 건은 미측정으로 센다. 잘못된 시각과 음수 경과 시간은 오류 수로 표시하고 평균에 넣지 않는다. 미측정을 0초 해결로 표시하지 않는다. 서버가 파일을 직접 검증한 시간이나 사용자 작업 시간으로 해석하지 않는다.

### 22.3 Evolution metrics

- 동일 잡음 pattern 재유입률
- policy feedback 적용 전후 발생량
- event source별 permanent memory 승격률
- 자동 생성 memory 중 승인된 파생 정책으로 검색에서 제외한 비율
- `[unknown agent]` 등 provenance 결손 비율
- 같은 candidate가 반복해서 다시 생성되는 비율

### 22.4 알림 조건

증가 추세는 판정이 끝난 최근 실행 10개와 직전 10개를 비교한다. 완료·부분 성공·실패·승인 대기를 포함하고 진행 중·취소 실행은 제외한다. 두 구간이 없으면 미측정으로 표시한다. 이 관측창은 임시 기본값이며 실제 운영 baseline으로 재검토한다.

Judge 실패율은 실패 호출 수를 전체 호출 수로 나눈 값이다. 고위험 제안 비율은 risk가 `low`, `medium`, `high`, `critical`로 분류된 제안 중 `high`·`critical`의 비율이다. 분류 coverage와 각 분모를 함께 제공한다. 분모가 없으면 증가를 판정하지 않는다. 화면에는 이전·최근 비율을 표시한다.

최근 구간의 서로 다른 두 실행 이상에서 활성화 budget 초과가 발생하면 반복 알림을 제공한다. 한 실행의 여러 초과 후보는 한 번으로 센다. 증가 알림은 관측된 비율 비교이며 통계적 유의성이나 원인을 뜻하지 않는다. 실행마다 입력·model·prompt가 다를 수 있으므로 원인은 run 이력에서 확인한다.

- validation failure
- index mismatch
- high-risk proposal 증가
- 동일 pattern의 재유입률이 줄지 않음
- LLM judge 실패율 증가
- 활성 정리 결과와 원본 입력 revision 불일치
- 활성화 budget 초과 반복
- rollback 발생

Budget 반복 알림은 이전 비교 구간 없이도 제공한다. 최근 최대 10개 완료 실행에서 서로 다른 두 실행의 초과 이력이 있으면 충분하다.

---

## 23. 사용자 경험

### 23.1 Run 결과

범위, 상태, 후보 수, 판정 수, 승인 대기·활성화·보류·실패·no-op 수, 검증 결과를 표시한다. 진행 중에는 run 상세의 `candidate_counts`를 주기적으로 조회하고 전체, 대기, 처리, 판정 완료, 보류, 실패 수와 진행률을 갱신한다. 원본 저장 건수 감소를 성과로 표시하지 않는다.

### 23.2 제안 검토

대표 원본, 모든 입력 원본과 버전, 새 정리 본문, claim별 원본 근거, 보존한 조건·예외, 제거한 반복 표현, 이유·불확실성, 정책·승인 필요 사유와 예상 검색 영향을 표시한다. 원본을 바꾸는 diff가 아니라 원본과 제안 본문 사이의 의미 차이를 보여준다. `needs_approval`에만 승인·거부 동작을 제공한다. `needs_review`는 보류 사유를 표시하고, dry-run proposal은 활성화되지 않는 미리보기임을 표시한다.

제안 카드에서 judge의 판단 이유와 실제 처리 오류를 구분해 표시한다. 판단 이유가 있어도 budget 초과나 검증 오류를 숨기지 않는다.

### 23.3 활성화와 취소

승인·활성화·취소 상태를 구분한다. 취소가 원본 삭제나 복구 작업이 아님을 표시한다. stale 결과에는 입력 변경 사유와 재검토 필요 여부를 표시하고, 원본을 바로 조회할 수 있게 한다.

### 23.4 No-op

조건이 다르거나 증거가 부족해 유효 읽기 결과를 바꾸지 않은 경우를 정상 결과로 표시한다. 본문 생성이나 자동 적용을 억지로 유도하지 않는다.

### 23.5 Project Overview

기존 Overview 화면에서 프로젝트 설명, 주요 결정, 최근 변경과 미해결 문제를 제공한다. 입력은 활성화된 정리 결과이며, 각 핵심 주장에서 원본으로 이동할 수 있어야 한다. 생성 시점, 포함한 정리 범위, 미검토 memory 여부, stale 상태와 재생성 동작을 제공한다. 활성 정리 결과가 없거나 일부만 검토했으면 해당 상태를 명시한다.

활성 정리 입력이 없으면 Generate를 비활성화하고 Reconciler 검토 화면으로 안내한다. 원본이 있어도 이 조건을 원본 부재로 설명하지 않는다. 생성 전에는 Overview 상태를 `current`로 표시하지 않는다. 활성 입력이 있고 캐시만 없으면 생성을 허용한다.

---

## 24. MVP 범위

### 24.1 포함

1. project-scoped 장기 memory 정리와 dry-run
2. semantic similarity, 같은 project·출처·anchor 기반 후보 구성
3. 기존 원본을 수정하지 않는 묶음별 대표 선택
4. 여러 원본에서 새 정리 본문 생성과 claim별 evidence 연결
5. 별도 SQLite 테이블의 결과·승인·활성화·취소·검증 이력
6. 원본 precondition, 재실행 멱등성, 동시 활성화 충돌 방지
7. `MERGE`·`SUPERSEDE`의 검증 후 자동 활성화와 명시적 보호 원본 제외
8. 활성화된 결과의 검색·context 반영과 원본 중복 노출 제거
9. 원본 조회·원본 기준 검색과 미정리 원본의 검색 유지
10. 원본 변경 시 결과 무효화와 재검토
11. 기존 Project Overview 화면을 유지한 생성 기반 교체
12. Overview의 근거·생성 시점·정리 범위·미검토·stale 표시
13. 구조·index·의미·검색·replay 검증, redaction과 payload 제한
14. no-op, 보류·실패 사유와 기존 LLM 경로 재사용

### 24.2 제외

- 기존 memory 행의 직접 수정·삭제·deprecated 전환
- 명시적으로 보호한 원본의 LLM 판단과 자동 활성화
- `NEEDS_REVIEW` 보류와 dry-run 미리보기의 자동 활성화
- observation·session·pin 수명주기 변경
- cross-project 정리와 분산 hub 정리
- 자동 ingest 정책 변경과 전체 Evolution Loop 운영
- 모순의 강제 해소와 장기 미사용만을 근거로 한 자동 검색 제외
- 별도 LLM provider 체계, 다중 judge 합의와 전면 dashboard 개편

### 24.3 성공 기준

원본 불변, 입력 근거와 대표 참조, 검색·context의 활성 결과 일치, 원본 조회, 반복 실행·활성화 시 중복 없음, 원본 변경 감지, 취소 후 읽기 일관성을 확인한다. 활성화된 새 정리 본문과 Overview를 실제로 조회할 수 있어야 한다. Overview가 미정리 범위를 전체 검토 결과로 제시하지 않아야 한다.

---

## 25. 단계별 출시 계획

Phase 0~3은 첫 출시 안의 순차 구현·검증 단계다. 새 정리 본문과 Overview 통합을 후속 출시로 미루지 않는다. Phase 4만 후속 범위다.

### Phase 0. 관측과 기준 수집

읽기 전용 detector, evidence, LLM 제안을 제공한다. 원본 불변, payload redaction, 실제 중복·모순·조건 차이 fixture와 query baseline을 확인한다. 읽기 결과는 바꾸지 않는다.

### Phase 1. 대표와 정리 결과 저장

원본을 묶고 대표를 선택한다. 새 종합 본문, claim별 evidence, 비활성 제안·활성화 이력을 저장한다. 근거 없는 claim 거부와 같은 입력의 결과 중복 방지를 확인한다.

### Phase 2. 검증된 활성화와 검색·context

검증된 결과만 활성화하고 파생 검색과 원본 조회를 연결한다. 취소, 원본 변경 감지, 동시 실행 충돌, index 실패 시 기존 읽기 유지, scope와 검색 회귀를 확인한다. 낮은 위험의 opt-in 자동 적용도 이 단계에서 검증한다.

### Phase 3. Project Overview 통합

기존 화면을 유지하고 활성화된 정리 결과를 종합하도록 생성 기반을 교체한다. 근거, 미검토 범위, 생성 시점과 stale 표시를 검증한다. 원본 변경·결과 취소·새 결과 활성화 후 Overview 의존성 갱신을 확인한다. 이 단계까지 통과해야 첫 출시 완료다.

### Phase 4. 후속 Evolution feedback

반복 잡음의 출처와 재유입을 분석해 ingest 정책 후보를 제안한다. 정책 적용에는 별도 승인과 취소 절차를 두고 효과를 측정한다. 기존 원본 불변 원칙은 유지한다.

---

## 26. 테스트 전략

### 26.1 단위·계약 테스트

- 후보 grouping과 묶음 내 대표 선택
- 같은 날 중복 후보의 누락 방지
- 원본 버전/hash, 관련 metadata·관계·anchor 변경 감지
- 입력 구성과 정책에 따른 중복 방지 키, 반복 승인·취소
- claim별 evidence, 조건·예외 보존과 잘못된 ID 거부
- project scope, provenance, 보호 대상과 opt-in 정책
- schema 실패, prompt injection, payload 제한과 redaction

### 26.2 LLM contract

고정 evidence에서 중복, 최신 근거, 다른 조건, 모순, 누락 provenance, 사용자 결정, 자동 생성 잡음을 구별하는지 확인한다. 정리 본문의 각 claim을 입력 원본으로 추적하고, 원본 수정 action이나 검증 없는 활성화를 허용하지 않는다. LLM 문장 자체의 동일성을 재실행 성공 기준으로 사용하지 않는다.

### 26.3 통합과 실패 테스트

임시 DB에서 run 생성부터 결과·승인·활성화·취소·receipt까지 확인한다. 각 단계 전후 원본 본문·상태·metadata·relation·anchor를 비교한다. worker 재시작, 동시 실행, provider timeout, embedding/index 실패, 원본 변경과 취소 도중의 적용을 검증한다. 실패한 proposal 때문에 원본이나 기존 유효 결과가 사라지면 안 된다.

### 26.4 검색·context와 Overview

scope별 recall, 중복률, 반환 개수, context token, 원본 인용을 baseline과 비교한다. 파생 본문을 검색 가능하게 하며 정리되지 않은 원본도 유지한다. Overview는 활성화된 유효 결과만 사용하고 부분 범위·미검토 여부·stale 상태를 표시해야 한다. 원본 변경, 결과 활성화·취소·무효화의 영향을 함께 확인한다.

고정 query suite의 hash와 원본 근거 coverage 회귀 수, 중복 결과 수, 검색·context의 추정 token 절감량을 프로젝트 단위로 기록한다. 원본 근거 coverage는 의미적 recall의 대체 지표로 표시하지 않는다.

2026-10-21 격리 DB의 `reconciler-web-worker-smoke`에서 세 query를 비교했다. Query는 `release notes Markdown`, `reviewer name test result`, `issue reference before release`다. Suite hash는 `b4863564b004c8d2e067d679d0afbbdaf15d0d68d1892c76d9fbce13fa26c011`이다.

각 query에서 raw 2건이 원본 2개를 인용한 정리 결과 1건으로 바뀌었다. 출처 coverage는 모두 100%를 유지했고 중복 슬롯 합계는 3개에서 0개로 줄었다. 검색·context의 추정 token은 각각 합계 282개에서 147개로 줄었다. Markdown 기록 시점과 issue reference·test result·reviewer name 조건이 정리 본문에 남는 것도 확인했다. 작은 합성 묶음의 결과이며 일반 검색 recall이나 실제 청구 token 수를 뜻하지 않는다.

같은 프로젝트에서 Overview 생성과 GET 캐시 조회를 확인했다. 활성 정리 입력 1개, 포함 원본 2개, 미검토 0개와 `stale=false`를 반환했다. 생성 시각 `2026-10-21T00:48:09.366744+00:00`과 본문을 캐시 조회에서 유지했다. 원본 인용 2개와 release note의 검증 조건을 보존했다. 브라우저 시각 검증은 로그인 완료 후 별도로 확인해야 한다.

실행 중인 HTTP MCP에서 Reconciler 도구 등록·결과 조회·잘못된 project 거부를 확인했다. 검색의 세 압축 형식과 compact context에서 전체 파생 ID와 원본 인용 2개를 유지했다. Raw compact context의 primary도 표시했고, raw·effective의 다른 project primary 요청은 거부했다.

### 26.5 기존 검증 기반

구현 시 `tests/test_reconcile.py`, `tests/test_curation.py`, `tests/test_overview_scheduler.py`와 실제 변경된 검색·context 경로의 기존 테스트를 사용한다. 적용 대상이 확정되면 해당 테스트와 `ruff check` 범위를 정한다. 문서만 수정하는 이번 작업에서는 제품 테스트를 실행한 것으로 간주하지 않는다.

### 26.6 운영 dry-run

project 하나에서 입력 범위와 query baseline을 고정한다. dry-run 후보와 정리 본문을 검토하고 실행 전 원본·유효 읽기 결과가 바뀌지 않았는지 확인한다. `decision`·`incident`를 포함한 검증 결과를 자동 활성화한 뒤 검색·context·Overview, replay와 취소를 확인한다. 명시적 보호 대상은 후보에서 제외한다. 실제 원본의 대량 변경은 이 절차에 포함하지 않는다.

---

## 27. 실패와 복구

### 27.1 LLM provider 실패

원본 저장과 기존 검색·context를 유지한다. 실패와 재시도 가능 여부를 기록하고 제한된 재시도를 수행한다. 기존 활성 결과는 유지하고 중복 작업·적용을 만들지 않는다.

### 27.2 원본 변경 충돌

활성화 전 불일치는 적용을 거부하고 stale 제안으로 남긴다. 활성 결과의 입력 불일치는 그 결과를 무효화하고 원본 기반 읽기 대상으로 되돌린다. 의존 Overview를 stale로 표시하고 최신 snapshot에서 재판정한다.

### 27.3 파생 index 실패

준비 또는 검증에 실패한 결과는 공개하지 않는다. 원본 index와 기존 유효 읽기 결과를 유지한다. 실패한 index 상태를 기록하고 복구 후 재검증한다. 부분 index가 준비됐다는 이유로 활성화 완료를 표시하지 않는다.

결과 검증 API는 원본 hash, FTS 본문·project, active·fallback vector의 존재·차원·유한 값·동일성, model metadata를 확인한다. Index 불일치가 확인된 활성 결과는 stale로 전환하고 원본 읽기를 복원한다. 검증 응답에는 실제 상태와 오류 목록을 반환한다.

기존 reindex 도구는 active 결과와 index 검증 실패로 stale이 된 결과를 처리한다. 원본이 바뀌거나 취소된 결과는 재활성화하지 않는다. 복구 적용 전후 원본·결과 revision을 다시 확인하고 FTS·vector 재구성과 `index_repair` 이력을 같은 transaction에 기록한다.

### 27.4 부분 run과 동시 실행

proposal 한 건은 원자적으로 활성화하거나 실패한다. run 전체에서는 완료·실패 항목을 분리하고 완료 receipt를 유지한다. 실패 항목만 안전하게 재시도한다. 같은 원본을 덮는 상충 결과는 동시 활성화하지 않고 검토 대상으로 남긴다.

### 27.5 잘못된 정리 본문

해당 파생 결과의 활성화를 취소한다. 원본은 수정되지 않았으므로 원본 본문 복구가 필요하지 않다. 다른 유효 결과와 원본으로 읽기 모델을 구성하고 의존 Overview를 stale로 표시한다. 입력·model·prompt·policy 이력을 보존해 원인을 조사한다.

### 27.6 Overview 생성 실패

실패를 기록하고 기존 Overview가 있으면 생성 시점과 stale 상태를 함께 제공한다. 없으면 미생성 상태를 표시한다. 비활성 제안이나 별도 원본 요약 경로로 조용히 대체하지 않는다. Overview 실패가 정리 결과의 검색·context 사용을 막아서는 안 된다.

---

## 28. 성공 지표

### 28.1 핵심 지표

1. **중복 노출 감소율**
   
   대표 query에서 동일 지식을 반복 노출하는 결과의 감소 비율

2. **Provenance 보존율**
   
   reconciliation 이후에도 source, session, anchor를 추적할 수 있는 memory 비율

3. **검색 회귀율**
   
   정리 후 expected 지식이 원본 또는 근거가 연결된 정리 본문으로 top-k에 유지되지 않은 query 비율

4. **재유입률**
   
   정리한 잡음 pattern이 설정 기간 안에 다시 permanent memory로 들어온 비율

5. **자동 적용 안전율**
   
   자동 적용 후 rollback 또는 사용자 거부로 되돌아간 proposal 비율

6. **No-op 정확도**
   
   no-op으로 남긴 candidate 중 나중에 사람이 실제 변경 불필요하다고 확인한 비율

7. **Context 효율**
   
   동일한 업무 query에 필요한 memory 수와 token 수의 변화

### 28.2 목표 예시

실제 수치는 baseline dry-run 이후 확정한다. 초기 목표 후보는 다음과 같다.

- 대표 query의 recall 저하 0%
- provenance coverage 100%
- relation orphan 0건
- 같은 입력 replay에서 중복 결과·중복 활성화 0건
- low-risk 자동 적용 rollback 1% 미만
- 반복 잡음 pattern 재유입률 Phase 4에서 baseline 대비 50% 이상 감소
- 중복 노출률 30% 이상 감소
- reconciliation이 hook hot path latency에 미치는 영향 0에 가까움

목표 수치는 품질 baseline을 측정한 뒤 재승인해야 한다. 초기부터 임의의 memory 감소율을 성공 기준으로 삼지 않는다.

---

## 29. 운영 정책 기본값

- Reconciler 비활성, 실행 시 dry-run 기본
- Reconciler는 설정된 공통 LLM을 사용하며, 프로젝트별 외부 전송 허용 제약을 두지 않음
- project scope 필수, cross-project와 원본 수정·영구 삭제 금지
- dry-run proposal은 preview 상태로 저장하며 승인·활성화하지 않음
- activation-capable run은 canonical 입력의 `MERGE`·`SUPERSEDE`를 category와 관계없이 검증 후 자동 활성화
- `reconciler_protected` 원본은 후보에서 제외
- `NEEDS_REVIEW`는 hold 상태로 두고 승인·활성화하지 않음
- noise suppression과 파생 relation의 자동 적용 정책은 기존 프로젝트 정책을 따름
- 원본 precondition, 적용 idempotency, provenance와 원본 조회 필수
- 구조·파생 index·검색·context·replay·Overview 검증 필수
- Curation은 현재 run의 후보 수와 진행률을 주기적으로 갱신
- 외부 LLM payload redaction과 길이 제한, 원문 evidence 전문 별도 복제 금지
- 기존 SQLite와 기존 LLM 설정·provider 경로 재사용

candidate 크기, payload 크기, 비용·시간·적용 수, 보존 기간의 실제 기본 수치는 baseline과 구현 제약을 확인한 뒤 확정한다. 이 절은 제품 기본 정책이며 새 config layer나 확정된 설정 키를 정의하지 않는다.

---

## 30. 주요 설계 결정

### D1. 원본을 보존하고 파생 본문을 별도로 저장한다

Reconciler는 기존 memory 본문·상태·metadata·relation·anchor를 수정하지 않는다. 원본은 정본이고 정리 본문은 근거가 연결된 파생 결과다. 감사 ledger와 검색용 정리 결과의 역할을 구별한다.

### D2. 대표 선택과 새 정리 본문 생성을 함께 지원한다

대표는 같은 지식의 묶음에 속한 기존 원본 중 한 개다. 여러 원본의 필요한 내용을 모은 새 정리 본문을 생성하고, 대표·모든 원본·claim 근거를 연결한다. 조건이 다른 후보나 no-op에 본문 생성을 강제하지 않는다.

### D3. 적용은 검증된 파생 결과의 활성화다

dry-run을 기본값으로 한다. activation-capable run에서는 canonical precondition, provenance, 충돌, budget, index 검증을 통과한 `MERGE`·`SUPERSEDE`를 category와 관계없이 자동 활성화한다. 명시적 보호 대상은 후보에서 제외하고 `NEEDS_REVIEW`는 활성화하지 않는다. 취소는 활성화 해제이며 원본 복구·삭제가 아니다.

### D4. 검색과 context는 같은 유효 결과를 사용한다

활성 정리 본문을 반환하고 묶음의 원본 중복 노출을 접는다. 미정리 원본은 유지하고 원본 조회·원본 기준 검색을 제공한다. 원본 scope와 provenance를 유지한다.

### D5. 원본 불변과 멱등성을 별도로 보장한다

원본을 건드리지 않아도 중복 정리 결과가 생길 수 있다. 입력 버전과 정책 기준의 중복 판정 방지, proposal 기준의 반복 적용 방지와 동시 실행 제약을 둔다.

### D6. Project Overview 통합은 첫 출시 범위다

기존 화면은 유지하고 활성화된 정리 결과를 종합하도록 생성 기반을 교체한다. 근거·시점·정리 범위·미검토 여부와 stale 상태를 표시한다. 원본 변경이나 입력 결과의 취소·무효화를 추적한다.

### D7. 모순과 불확실성을 보존한다

최신이라는 이유로 정답을 확정하지 않는다. 조건·시점·예외를 보존하고 근거가 부족하면 보류한다. no-op은 정상 결과다.

### D8. 기존 실행 기반을 재사용하고 범위를 제한한다

기존 SQLite·Database 계층, LLM resolver·provider, MCP 공통 경로를 따른다. 첫 출시는 project 내 장기 memory 정리이며 observation·session·pin은 근거로만 읽는다. ingest 정책 변경과 전체 Evolution Loop는 후속 범위다.

---

## 31. 구현 설계에서 확정할 사항

다음은 합의한 원본 보존·검색 반영·Overview 통합을 바꾸지 않는 구현 세부다.

1. 별도 SQLite 테이블·열·index·migration과 원본 입력 revision 표현
2. 입력 묶음 중복 방지 키, 활성화 transaction과 동시 worker 제약
3. candidate 임계값, 묶음 크기와 payload·비용·시간 budget
4. 파생 본문의 FTS/vector 검색, scope별 검색·context 통합과 공개 경계
5. 원본 기준 검색과 파생 결과 식별자의 기존 응답·인용 호환성
6. claim별 근거 표현, redaction과 ledger 보존 기간
7. 기존 Reconcile·Curation 제안의 전환과 레거시 승인 기능 경계
8. 기존 Overview 응답·스케줄과의 호환성, 범위·미검토 계산과 무효화 방식
9. 기존 relation type과 파생 의미 관계의 매핑
10. 사용자 검토 화면, MCP·CLI의 최소 노출 범위와 정확한 API schema
11. 기존 입력 변경 이벤트와 읽기 시 유효성 검사를 조합하는 감지 방식
12. 대표 query fixture, 의미 보존 평가와 출시 기준 수치

외부 provider 체계 신설, 별도 DB 파일, 원본 직접 변경, Overview 통합의 후속 연기는 첫 출시 기본안으로 남겨두지 않는다. 필요하면 제품 범위 변경으로 다시 합의한다.

---

## 32. 최종 제품 계약

Memory Reconciler는 project 내 기존 memory를 읽고 원본을 수정하지 않는다. 관련 원본을 묶고 그 안에서 대표를 선택하며 여러 원본의 사실·조건·예외를 모은 새 정리 본문을 별도 SQLite 테이블에 저장한다. 각 핵심 claim은 원본 ID와 입력 버전으로 추적할 수 있어야 한다.

정리안은 scope·precondition·provenance·idempotency 검사를 통과한 뒤 활성화된다. `MERGE`·`SUPERSEDE`는 live run에서 category와 관계없이 자동 활성화하고, 명시적으로 보호한 원본은 후보에서 제외한다. 검색과 context는 같은 유효 정리 결과를 사용해 원본 중복 노출을 접으며, 미정리 원본과 원본 조회를 유지한다. 적용 취소와 원본 변경은 파생 결과의 활성화·유효성 및 Overview 갱신 상태에 반영한다.

Project Overview는 첫 출시부터 활성화된 정리 결과를 프로젝트 단위로 종합한다. 기존 화면을 유지하고 근거 원본·생성 시점·정리 범위·미검토 여부를 표시한다. 기존 LLM 설정과 provider를 재사용한다. observation·session·pin은 판단 근거로만 참조하고 수집 정책의 자동 변경은 후속 범위로 둔다.

성공은 원본 건수 감소가 아니다. 원본 불변, 줄어든 중복 노출, 보존된 조건과 provenance, 드러난 모순, 일관된 검색·context·Overview, 반복 실행·적용 안전성으로 판단한다.
