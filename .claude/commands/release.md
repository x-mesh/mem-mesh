---
description: git-kit 기반 mem-mesh 릴리스 — preflight → version bump → CHANGELOG → commit → develop→main merge → tag → push
argument-hint: [x.y.z]
---

# /release — mem-mesh 릴리스 워크플로

`$ARGUMENTS`(`x.y.z`)로 릴리스한다. 버전 인자가 없으면 사용자에게 먼저 묻는다.

이 레포는 **git-kit driven**이고, 버전 단일 소스는 `pyproject.toml`이다(`app.core.version`이 런타임에 읽음). `make release`가 있지만 raw git을 쓰므로, 아래는 동일 흐름을 git-kit으로 수행한다. 항상 `export GK_AGENT=1` 후 `git-kit`(짧은 `gk` 아님)로 호출하고, 실패 시 `error.remedies[0]`를 따른다.

## 출력 가드

- `call`, `tool call`, `Bash call` 같은 tool-call placeholder를 단독 줄로 출력하지 않는다.
- 도구가 필요하면 visible text에 placeholder를 쓰지 말고 즉시 도구를 호출한다.
- 도구 호출 전후에는 사용자가 읽을 정상 문장만 남긴다.

## 0. 전제 확인 (먼저)

```bash
export GK_AGENT=1
git-kit context --include=diff,log,release
```
- 현재 브랜치(보통 `develop`), base(`main`) drift, dirty 상태 파악.
- **`latest_tag`가 요청 버전과 같으면 중단**하고 사용자에게 알린다(중복 릴리스 방지). 태그가 이미 있는데 pyproject만 어긋난 경우라면 release가 아니라 정합성 복구이므로 별도로 처리.
- base가 diverge면 `git-kit pull --with-base`(FF-only)를 먼저.

## 1. Preflight (게이트)

```bash
git-kit ship --preflight   # 설정된 lint/test를 working tree에서 실행, 태그/푸시 없음
```
실패하면 여기서 멈추고 고친다. 통과 전엔 다음 단계 금지.

> ⚠️ 테스트가 임베딩/리랭커 모델을 로드한다면 CPU(맥)에서 무거울 수 있다(CLAUDE.md L1). 무거운 측정성 테스트는 피하고, 최소 `python -c "from app.web.app import app"` import check은 항상 통과시킨다.

## 2. Version bump

```bash
make bump V=x.y.z
python -c "from app.core.version import __VERSION__; print(__VERSION__)"   # 런타임 반영 확인
```

## 3. CHANGELOG

`CHANGELOG.md` 최상단에 `## [x.y.z] - YYYY-MM-DD` 항목이 있는지 확인. 없으면 직전 태그 이후 커밋(`git-kit context --include=release`)을 근거로 `Added` / `Changed` / `Fixed` / `Performance` 섹션을 Keep a Changelog 형식으로 작성한다. **WHY(배경)를 포함**하고, 변경된 핵심 파일 경로를 명시.

## 4. Commit

```bash
git-kit commit -f          # pyproject.toml + CHANGELOG.md 를 conventional commit으로
```
릴리스 커밋 메시지는 `chore(release): mem-mesh@x.y.z`. (Makefile은 `release:` prefix를 쓰지만 git-kit은 conventional type만 허용하므로 `chore(release)` scope로 표기.) 무관한 변경이 섞였으면 `git-kit commit --plan-template`로 그룹을 분리.

## 5. Ship (merge → tag → push)

```bash
git-kit ship --dry-run --json   # 추론 version·CHANGELOG draft·merge_to_base 검토
```
계획이 의도와 맞으면:
```bash
git-kit ship -y    # preflight → version/tag → push → CI watch → artifact verify
```
- `develop` 등 non-base 브랜치면 ship이 base(`main`)로 FF한 뒤 태그한다. 히스토리가 diverge면 멈추므로 0단계의 `pull --with-base`를 선행.
- 태그 push 후 GitHub Actions가 PyPI publish.
- CI watch 생략은 `--wait=false`.

## 가드

- **되돌리기 어려운 단계(push, 태그)는 사용자 확인 없이 강행 금지** — 명시 요청 시에만 `ship -y`/`--push`.
- API키·토큰·PII 커밋 금지(push 전 git-kit이 secret scan하지만, 코드 스니펫의 민감 값은 사전에 `<REDACTED>`).
- 실패하면 `git-kit context`로 `failed_step`/resume 명령을 확인하고 그 remedy를 실행. 어설픈 raw git 복구 금지.
