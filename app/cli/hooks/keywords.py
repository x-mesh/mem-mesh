"""Single source of truth for keyword matching patterns used in hook scripts.

Two consumers share the same patterns:

1. Shell hooks (legacy / Cursor / local mode) — the KEYWORD_MATCHER_BLOCK is
   injected via the __KEYWORD_MATCHER__ placeholder at install time. It reads
   from stdin and prints a category name (or 'SKIP').

       CATEGORY=$(python3 -c "
       __KEYWORD_MATCHER__
       " <<< "$MESSAGE" 2>/dev/null) || CATEGORY="SKIP"

2. HTTP hooks — the server imports ``match_category()`` directly so the same
   classification runs server-side without spawning python3 on the client.

Both paths MUST stay behaviourally identical; edit the patterns in
``_COMPLETION_PATTERNS`` / ``_CATEGORY_RULES`` and keep the shell block in sync.

Classification notes
--------------------
* Rule **order is the tie-break**: when two categories match the same number of
  patterns, the one listed earlier wins (the score loop uses ``>``). The list is
  ordered most-specific → least, with ``bug`` deliberately late. bug symptom
  words (error/exception/crash) are high-signal enough to win on score alone, so
  demoting bug in ties stops generic "수정했습니다" turns from defaulting to bug.
* bug has **no standalone fix-verb pattern**. A bare "수정/fix/해결" is not a bug
  signal — it must co-occur with a symptom word. The old standalone pattern
  matched nearly every coding turn and was the root cause of the bug-category
  over-classification (52% of all memories).
"""

import re

_COMPLETION_PATTERNS = [
    r"(완료|했습니다|합니다|됩니다|done|finished|completed|resolved|fixed)",
    r"(수정|변경|추가|삭제|생성|구현|적용|배포|설치)",
    r"(updated|changed|added|removed|created|implemented|deployed|installed)",
    r"(이제|now|successfully|정상)",
    r"(커밋|commit|push|merge|PR|pull request)",
]

# NOTE: order = tie-break priority (earlier wins on equal score). Keep in sync
# with ``category_rules`` inside KEYWORD_MATCHER_BLOCK below.
_CATEGORY_RULES = [
    (
        "incident",
        [
            r"(장애|incident|outage|다운타임|downtime)",
            r"(서버|server|서비스|service).{0,30}(죽|down|중단|stop)",
            r"\b(rollback|롤백)\b",
            r"(production|프로덕션|운영).{0,40}(issue|error|장애|문제)",
        ],
    ),
    (
        "decision",
        [
            r"(결정|decision|decided|chose|선택|채택)",
            r"(아키텍처|architecture|설계|design).{0,60}(변경|변환|전환|decided|chose)",
            r"(전환|migration|마이그레이션|migrate)",
            r"(대신|instead|rather).{0,40}(사용|use)",
            r"(방식|approach|strategy).{0,40}(변경|바꾸|switch)",
            r"\b(breaking[\s-]?change|호환[\s-]?변경)\b",
            r"(trade[\s-]?off|트레이드)",
            r"(선택|chose|picked).{0,40}(over|instead|대신|보다)",
            r"(replace|교체|대체).{0,40}(with|로|으로)",
            r"\b(deprecated?|폐기)\b",
            r"(의존성|dependency|deps).{0,40}(추가|변경|제거|added|changed|removed|upgrade)",
        ],
    ),
    (
        "code_snippet",
        [
            r"(구현|implement|개발|develop)",
            r"(추가|add|생성|create).{0,60}(기능|feature|함수|function|메서드|method|클래스|class|API|엔드포인트|endpoint)",
            r"(리팩토링|refactor|개선|improve|최적화|optimize)",
            r"(배포|deploy|릴리즈|release)",
            r"\bfeat:\s",
            r"\brefactor:\s",
            r"\bperf:\s",
            r"implementation\s+complete",
            r"구현\s*(완료|했습니다|끝|했음)",
            r"(새로운|new)\s+(모듈|module|파일|file|클래스|class|함수|function)",
            r"\d+\s+passed",
            r"(성능|performance).{0,40}(개선|improve|최적화|optimiz)",
        ],
    ),
    (
        "bug",
        [
            # Symptom words: the primary, high-signal bug indicator (standalone).
            r"(버그|bug|에러|error|오류|exception|crash|stack\s*trace|traceback|"
            r"TypeError|ValueError|KeyError|NullPointer|segfault|panic)",
            # A fix verb only counts as a bug when it co-occurs with a symptom —
            # replaces the old over-broad standalone (수정|fix|해결|patch|debug).
            r"(버그|bug|에러|error|오류|exception|crash|문제|issue|실패|fail)"
            r".{0,40}(수정|fix|해결|resolved|patch|고침|고쳤|패치)",
            r"\b(hotfix|핫픽스)\b",
            r"\bfix:\s",
            r"(문제|issue|problem).{0,40}(해결|수정|fix)",
            r"(실패|fail).{0,40}(수정|fix|해결)",
            r"(root\s*cause|원인).{0,40}(was|은|는|확인|파악)",
            r"(regression|리그레션)",
            r"(보안|security).{0,40}(취약|vulnerab|fix|수정|패치|patch)",
            r"(디버그|debug).{0,40}(결과|원인|찾|발견|해결)",
        ],
    ),
    (
        "idea",
        [
            r"(아이디어|idea|제안|suggest|proposal)",
            r"(고려|consider|검토|review).{0,40}(해볼|해보|worth)",
            r"(향후|future|나중에|later).{0,60}(개선|improvement|고려|consider|추가)",
            r"(개선\s*사항|improvement).{0,40}(제안|suggest|필요|need)",
        ],
    ),
]


def match_category(message: str, extra_kw: str = "") -> str:
    """Classify an assistant message into a memory category.

    Mirrors the logic embedded in ``KEYWORD_MATCHER_BLOCK``: a two-pass scan
    (completion detection, then category scoring). Returns ``"SKIP"`` when the
    message shows no completion signal or no category pattern matches.

    Tie-break: the highest-scoring category wins; on a tie the earlier rule in
    ``_CATEGORY_RULES`` wins (the ``>`` comparison never overwrites an equal
    score). ``bug`` sits late in the list on purpose — see module docstring.

    Args:
        message: The assistant message to classify.
        extra_kw: Optional comma-separated ``category:pattern`` pairs (same
            format as the ``MEM_MESH_HOOK_EXTRA_KEYWORDS`` env var).
    """
    msg = (message or "").lower()
    if not msg:
        return "SKIP"

    if not any(re.search(p, msg) for p in _COMPLETION_PATTERNS):
        return "SKIP"

    # Copy rules so extra keywords never mutate the module-level patterns.
    rules = [(cat, list(patterns)) for cat, patterns in _CATEGORY_RULES]

    if extra_kw:
        for pair in extra_kw.split(","):
            pair = pair.strip()
            if ":" in pair:
                cat, pat = pair.split(":", 1)
                for rule_cat, rule_patterns in rules:
                    if rule_cat == cat.strip():
                        rule_patterns.append(pat.strip())
                        break

    best_cat = "SKIP"
    best_score = 0
    for cat, patterns in rules:
        score = sum(1 for p in patterns if re.search(p, msg))
        if score > best_score:
            best_score = score
            best_cat = cat

    return best_cat if best_score >= 1 else "SKIP"


# fmt: off
KEYWORD_MATCHER_BLOCK = r"""import sys, re, os

msg = sys.stdin.read().lower()
extra_kw = os.environ.get('EXTRA_KW', '')

# Pass 1: completion indicators (must match at least one)
completion = [
    r'(완료|했습니다|합니다|됩니다|done|finished|completed|resolved|fixed)',
    r'(수정|변경|추가|삭제|생성|구현|적용|배포|설치)',
    r'(updated|changed|added|removed|created|implemented|deployed|installed)',
    r'(이제|now|successfully|정상)',
    r'(커밋|commit|push|merge|PR|pull request)',
]

has_completion = any(re.search(p, msg) for p in completion)
if not has_completion:
    print('SKIP')
    sys.exit(0)

# Pass 2: categorize (each pattern is a vote; highest score wins).
# Order = tie-break priority (earlier wins on equal score); bug sits late so a
# bare fix verb does not default a turn to bug.
category_rules = [
    # incident: outage/incident (most severe — wins ties)
    ('incident', [
        r'(장애|incident|outage|다운타임|downtime)',
        r'(서버|server|서비스|service).{0,30}(죽|down|중단|stop)',
        r'\b(rollback|롤백)\b',
        r'(production|프로덕션|운영).{0,40}(issue|error|장애|문제)',
    ]),
    # decision: architecture/design choices
    ('decision', [
        r'(결정|decision|decided|chose|선택|채택)',
        r'(아키텍처|architecture|설계|design).{0,60}(변경|변환|전환|decided|chose)',
        r'(전환|migration|마이그레이션|migrate)',
        r'(대신|instead|rather).{0,40}(사용|use)',
        r'(방식|approach|strategy).{0,40}(변경|바꾸|switch)',
        r'\b(breaking[\s-]?change|호환[\s-]?변경)\b',
        r'(trade[\s-]?off|트레이드)',
        r'(선택|chose|picked).{0,40}(over|instead|대신|보다)',
        r'(replace|교체|대체).{0,40}(with|로|으로)',
        r'\b(deprecated?|폐기)\b',
        r'(의존성|dependency|deps).{0,40}(추가|변경|제거|added|changed|removed|upgrade)',
    ]),
    # code_snippet: implementation
    ('code_snippet', [
        r'(구현|implement|개발|develop)',
        r'(추가|add|생성|create).{0,60}(기능|feature|함수|function|메서드|method|클래스|class|API|엔드포인트|endpoint)',
        r'(리팩토링|refactor|개선|improve|최적화|optimize)',
        r'(배포|deploy|릴리즈|release)',
        r'\bfeat:\s',
        r'\brefactor:\s',
        r'\bperf:\s',
        r'implementation\s+complete',
        r'구현\s*(완료|했습니다|끝|했음)',
        r'(새로운|new)\s+(모듈|module|파일|file|클래스|class|함수|function)',
        r'\d+\s+passed',
        r'(성능|performance).{0,40}(개선|improve|최적화|optimiz)',
    ]),
    # bug: error/fix related (symptom required; no standalone fix verb)
    ('bug', [
        r'(버그|bug|에러|error|오류|exception|crash|stack\s*trace|traceback|TypeError|ValueError|KeyError|NullPointer|segfault|panic)',
        r'(버그|bug|에러|error|오류|exception|crash|문제|issue|실패|fail).{0,40}(수정|fix|해결|resolved|patch|고침|고쳤|패치)',
        r'\b(hotfix|핫픽스)\b',
        r'\bfix:\s',
        r'(문제|issue|problem).{0,40}(해결|수정|fix)',
        r'(실패|fail).{0,40}(수정|fix|해결)',
        r'(root\s*cause|원인).{0,40}(was|은|는|확인|파악)',
        r'(regression|리그레션)',
        r'(보안|security).{0,40}(취약|vulnerab|fix|수정|패치|patch)',
        r'(디버그|debug).{0,40}(결과|원인|찾|발견|해결)',
    ]),
    # idea: suggestions
    ('idea', [
        r'(아이디어|idea|제안|suggest|proposal)',
        r'(고려|consider|검토|review).{0,40}(해볼|해보|worth)',
        r'(향후|future|나중에|later).{0,60}(개선|improvement|고려|consider|추가)',
        r'(개선\s*사항|improvement).{0,40}(제안|suggest|필요|need)',
    ]),
]

# Add extra keywords from env
if extra_kw:
    for pair in extra_kw.split(','):
        pair = pair.strip()
        if ':' in pair:
            cat, pat = pair.split(':', 1)
            for rules in category_rules:
                if rules[0] == cat.strip():
                    rules[1].append(pat.strip())
                    break

# Score each category: count how many patterns match
best_cat = 'SKIP'
best_score = 0
for cat, patterns in category_rules:
    score = sum(1 for p in patterns if re.search(p, msg))
    if score > best_score:
        best_score = score
        best_cat = cat

# Require at least 1 category pattern match
if best_score < 1:
    best_cat = 'SKIP'

print(best_cat)"""
# fmt: on
