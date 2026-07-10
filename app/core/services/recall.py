"""세션 재개 시 큐레이션 메모리를 surface하는 헬퍼 (read-only).

``session_resume`` / ``SessionStart`` 훅은 그동안 pins만 반환했다. 저장된
17k+ 메모리 코퍼스가 정규 세션 루프에서 한 번도 읽히지 않아(운영 dead_ratio
≈0.999) 시스템이 "쓰기 전용 싱크"로 전락한 것이 핵심 문제였다.

이 헬퍼는 열린 작업(open/in_progress pin) 맥락을 쿼리로 관련 메모리를 검색해
세션 시작 시 함께 노출함으로써 읽기 루프를 닫는다.

설계 원칙:
- **read-only**: ``search(record_access=False)`` 로 호출해 access_count를
  올리지 않는다. 자동 surface가 recall 지표를 부풀리면 안 되기 때문이다.
  실제 recall은 에이전트가 직접 ``search`` 할 때만 집계된다.
- **큐레이션 우선**: 대화 덤프(Q:/A:)·노이즈를 피하려 가치 높은 카테고리만
  노출한다(``_SURFACE_CATEGORIES``). 미래에 source/importance 필터를 추가할
  수 있다.
- **best-effort**: 검색 실패는 절대 세션 재개를 깨뜨리지 않는다 — 빈 목록 반환.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 재사용 가치가 높은 카테고리만 surface (bug 50% 편향·대화 덤프 노이즈 회피).
_SURFACE_CATEGORIES: Set[str] = {"decision", "code_snippet", "incident"}


async def surface_relevant_memories(
    search_service: Any,
    project_id: str,
    *,
    query: str,
    limit: int = 3,
    min_score: float = 0.35,
    categories: Optional[Set[str]] = None,
) -> List[dict]:
    """열린 작업 맥락으로 관련 큐레이션 메모리를 read-only로 surface한다.

    Args:
        search_service: ``UnifiedSearchService`` (또는 ``search`` 시그니처 호환).
            None이면 빈 목록.
        project_id: 검색 스코프.
        query: 시드 쿼리 (보통 열린 pin 내용 결합). 비면 빈 목록.
        limit: 반환할 최대 메모리 수.
        min_score: 최소 유사도 (0~1). 약한 매치 컷오프.
        categories: surface 허용 카테고리. None이면 ``_SURFACE_CATEGORIES``.

    Returns:
        list[dict]: {id, category, content(≤240자), created_at(YYYY-MM-DD), score}
    """
    if search_service is None or not query or not query.strip():
        return []

    cats = categories if categories is not None else _SURFACE_CATEGORIES

    try:
        result = await search_service.search(
            query=query[:300],
            project_id=project_id,
            limit=max(limit * 3, 8),
            sort_by="relevance",
            sort_direction="desc",
            search_mode="hybrid",
            record_access=False,  # read-only: surfacing != genuine recall
        )
    except Exception as e:  # noqa: BLE001 — best-effort, never break resume
        logger.debug(f"surface_relevant_memories search failed: {e}")
        return []

    items = getattr(result, "results", None) or []

    # Selection-stage stale gate (t12): drop memories a client verified as stale
    # (anchors rotted) so they never reach the SessionStart injection or the
    # session_resume tool payload. Weak/aged anchors are NOT dropped here — the
    # formatter flags them with a warning token instead. Best-effort: a missing
    # db handle or query failure yields an empty set and changes nothing.
    stale = await _stale_id_set(
        getattr(search_service, "db", None),
        [
            (r.get("id") if isinstance(r, dict) else getattr(r, "id", None))
            for r in items
        ],
    )

    out: List[dict] = []
    seen: Set[str] = set()
    for r in items:
        rid = getattr(r, "id", None) if not isinstance(r, dict) else r.get("id")
        if rid is None or rid in seen or rid in stale:
            continue
        cat = (
            getattr(r, "category", None)
            if not isinstance(r, dict)
            else r.get("category")
        )
        if cats and cat not in cats:
            continue
        score = (
            getattr(r, "similarity_score", 0.0)
            if not isinstance(r, dict)
            else r.get("similarity_score", 0.0)
        ) or 0.0
        if float(score) < min_score:
            continue
        content = (
            getattr(r, "content", "")
            if not isinstance(r, dict)
            else r.get("content", "")
        ) or ""
        created = (
            getattr(r, "created_at", "")
            if not isinstance(r, dict)
            else r.get("created_at", "")
        ) or ""
        seen.add(rid)
        out.append(
            {
                "id": rid,
                "category": cat,
                "content": content[:240],
                "created_at": str(created)[:10],
                "score": round(float(score), 3),
            }
        )
        if len(out) >= limit:
            break
    return out


# ───────────────────── shared injection formatter ─────────────────────
#
# session_start(SessionStart)와 user_prompt_submit(UserPromptSubmit) 두 훅은
# 그동안 각자 관련 메모리를 자체 문자열로 조립했다(중복 로직). 아래 헬퍼는 그
# "표시(display)" 단계만 한곳으로 모은다 — 선별(카테고리/threshold/limit)은 여전히
# 각 훅의 책임이고, 포맷터는 이미 선별된 항목을 받아 라인으로만 바꾼다.
#
# 데이터 배선: 결과 id 목록으로 memory_enrichment(title/abstract)를 IN 배치로 1회
# 조회해 dict에 병합한다(검색 경로 3종은 무변경).
#
# 출력 포맷(t18): ``- [category] (나이 · 출처) title — abstract요약``
# 문장 중간 절단과 원문 덤프가 주입 컨텍스트 오염의 직접 원인이므로, LLM 호출 없이
# 저장된 데이터와 순수 파싱만으로 3단 fallback을 적용한다:
#   1. enrichment title/abstract 존재  → title + abstract 요약 (source=enriched)
#   2. 구조 추출: 마크다운 heading/첫 줄 → title, 이어지는 첫 문장 → 요약 (extracted)
#   3. 자유 텍스트: 앞부분을 문장 경계에서 절단 (extracted)
# 어떤 경우에도 문장 중간에서 자르지 않는다 — 경계를 못 찾으면 마지막 공백에서
# 자르고 "…"를 붙인다. 코드 블록(```)은 요약 대상에서 제외하고, Q:/A: 대화 덤프는
# 질문 첫 문장만 노출한다.

_ENRICHMENT_TABLE = "memory_enrichment"

# 요약/제목 길이 상한(대략). 문장 경계 우선이라 정확히 이 값에서 끊기지는 않는다.
_SUMMARY_LIMIT = 200
_TITLE_LIMIT = 80

# 한국어 종결 어미(다/요/음/함). 마침표 없이 공백/줄끝에서 문장이 끝나는 노트체를
# 함께 처리한다. 영어는 .!? 로 종결.
_KO_ENDINGS = "다요음함"
_SENT_CLOSERS = "\"')]}»”’"


def _strip_code_blocks(text: str) -> str:
    """펜스 코드 블록(```...```)을 제거해 코드가 요약에 덤프되지 않게 한다.

    ``` 로 분할해 짝수 인덱스(코드 바깥)만 유지한다. 닫히지 않은 펜스는 여는 ``` 이후를
    모두 코드로 간주해 버린다("건너뜀"). 줄 구조는 유지해 heading 추출을 깨지 않는다.
    """
    if "```" not in text:
        return text
    parts = text.split("```")
    return "\n".join(parts[i] for i in range(0, len(parts), 2))


def _normalize(text: str) -> str:
    """코드 블록 제거 + 공백 단일화. 주입 bullet은 한 줄이라 개행도 공백으로 접는다."""
    return re.sub(r"\s+", " ", _strip_code_blocks(text or "")).strip()


def _sentence_boundaries(text: str):
    """문장 종결 위치(경계 다음 인덱스)를 순서대로 yield.

    - 영어/공통: ``.`` ``!`` ``?`` 뒤가 문자열 끝·공백·닫는 따옴표/괄호일 때.
    - 한국어: 종결 어미(다/요/음/함) 뒤가 공백 또는 문자열 끝일 때. 마침표가 뒤따르면
      해당 위치는 마침표 규칙이 처리하므로 여기서 중복 yield 하지 않는다.
    """
    n = len(text)
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < n else ""
        if ch in ".!?":
            if nxt == "" or nxt.isspace() or nxt in _SENT_CLOSERS:
                yield i + 1
        elif ch in _KO_ENDINGS:
            if nxt == "" or nxt.isspace():
                yield i + 1


def _clip(text: str, max_len: int) -> str:
    """max_len 이내에서 문장 경계로 절단(자유 텍스트/abstract 요약용).

    경계를 못 찾으면 마지막 공백에서 자르고 "…"를 붙인다 — 절대 단어/문장 중간에서
    끊지 않는다.
    """
    text = _normalize(text)
    if len(text) <= max_len:
        return text
    window = text[:max_len]
    last = -1
    for b in _sentence_boundaries(window):
        last = b
    if last > 0:
        return window[:last].rstrip()
    sp = window.rstrip().rfind(" ")
    if sp > 0:
        return window[:sp].rstrip() + "…"
    return window.rstrip() + "…"


def _first_sentence(text: str, max_len: int) -> str:
    """첫 문장 하나를 반환. 첫 문장이 max_len을 넘으면 :func:`_clip` 로 안전 절단."""
    text = _normalize(text)
    if not text:
        return ""
    for b in _sentence_boundaries(text):
        if b <= max_len:
            return text[:b].rstrip()
        break
    return _clip(text, max_len)


def _cap(text: str, limit: int) -> str:
    """제목용 하드 캡 — limit 초과 시 잘라내고 "…" 표시(제목은 라벨이라 경계 무관)."""
    text = text.strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _derive_from_content(
    content: str, *, title_limit: int, summary_limit: int
) -> Tuple[str, str, str]:
    """enrichment가 없을 때 원문에서 (title, summary, source)를 순수 파싱으로 도출.

    Tier 2(구조 추출) vs Tier 3(자유 텍스트)를 판별하고, Q:/A: 대화 덤프는 질문 첫
    문장만 노출한다. source는 두 경우 모두 ``extracted``.
    """
    content = _strip_code_blocks(content or "")
    first_line = next((ln for ln in content.splitlines() if ln.strip()), "")
    head = first_line.strip()

    # Q:/A: 대화 덤프 → 질문 첫 문장만 (A: 이하 덤프 노출 금지).
    qm = re.match(r"(?i)^q\s*[:：]\s*(.+)$", head)
    if qm:
        question = qm.group(1).strip()
        return _first_sentence(question, summary_limit), "", "extracted"

    is_heading = head.startswith("#")
    rest = ""
    if first_line:
        cut = content.find(first_line) + len(first_line)
        rest = content[cut:]
    rest_norm = _normalize(rest)

    # Tier 2(구조): 마크다운 heading, 또는 종결 부호 없는 짧은 첫 줄 + 뒤따르는 본문.
    ends_sentence = head.rstrip().endswith((".", "!", "?", "…"))
    title_like = is_heading or (
        len(head) <= title_limit and not ends_sentence and bool(rest_norm)
    )
    if title_like:
        title = _cap(head.lstrip("#").strip(), title_limit)
        return title, _first_sentence(rest_norm, summary_limit), "extracted"

    # Tier 3(자유 텍스트): 앞부분을 문장 경계에서 절단.
    return _clip(content, summary_limit), "", "extracted"


def _parse_created_at(created_at: Any) -> Optional[datetime]:
    """created_at(ISO8601 또는 YYYY-MM-DD)을 naive datetime으로 파싱(불가 시 None)."""
    raw = str(created_at or "").strip()
    if not raw:
        return None
    iso = raw.replace("Z", "+00:00")
    dt: Optional[datetime] = None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        try:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _age_days(created_at: Any, *, now: Optional[datetime] = None) -> Optional[int]:
    """created_at 기준 경과 일수(정수). 파싱 불가면 None, 미래면 음수."""
    dt = _parse_created_at(created_at)
    if dt is None:
        return None
    ref = now or datetime.now()
    if ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    return (ref.date() - dt.date()).days


def _relative_age(created_at: Any, *, now: Optional[datetime] = None) -> str:
    """created_at 기준 한국어 상대 나이: 오늘 / N일 전 / N주 전 / N개월 전.

    파싱 불가·미래 시각은 각각 ``""`` / "오늘" 로 graceful.
    """
    days = _age_days(created_at, now=now)
    if days is None:
        return ""
    if days <= 0:
        return "오늘"
    if days < 7:
        return f"{days}일 전"
    if days < 30:
        return f"{days // 7}주 전"
    return f"{days // 30}개월 전"


# ───────────────────── stale-anchor injection gate (t12) ─────────────────────
#
# 앵커 기반 2단 stale 판정을 주입에 반영한다:
#   - 강한 신호: 클라이언트가 로컬에서 anchors(file_paths 존재·commit 도달성)를 검증해
#     ``report_anchor_status``로 보고한 결과(memories.stale_status). 'stale'은 주입에서
#     완전히 제외한다(선별 단계 필터: filter_injectable / surface_relevant_memories).
#   - 약한 신호: 서버는 git 접근이 불가하므로, commit_hash 앵커를 가진 미검증 메모리가
#     오래됐으면(기본 90일, 설정화) 라인에 ``· 미검증 anchor`` 경고 토큰만 붙인다(제외 X).
#
# 저장 컬럼(stale_status) 없이 aged 계산은 조회 시점에 anchors+created_at로만 한다.

_STALE_STATUS_STALE = "stale"
_STALE_STATUS_FRESH = "fresh"
_AGED_ANCHOR_TOKEN = "미검증 anchor"
_STALE_ANCHOR_AGE_DAYS_DEFAULT = 90


def _aged_anchor_age_days() -> int:
    """aged-anchor 임계(일). settings.stale_anchor_age_days 우선, 실패 시 기본 90."""
    try:
        from ..config import get_settings

        return int(get_settings().stale_anchor_age_days)
    except Exception:  # noqa: BLE001 — config read must never break formatting
        return _STALE_ANCHOR_AGE_DAYS_DEFAULT


def _is_aged_anchor(item: dict, *, now: Optional[datetime], age_days: int) -> bool:
    """commit_hash 앵커를 가진 미검증 메모리가 age_days 이상 오래됐는지(약한 신호).

    stale_status='fresh'(클라이언트 최신 검증)면 경고하지 않고, 'stale'은 애초에 주입
    선별에서 제외되므로 여기 도달하면 안 되지만 방어적으로 False. commit_hash가 없는
    앵커(파일 경로만 등)는 도달성 판단 근거가 약해 경고하지 않는다.
    """
    status = item.get("stale_status")
    if status in (_STALE_STATUS_FRESH, _STALE_STATUS_STALE):
        return False
    anchors = item.get("anchors")
    if not isinstance(anchors, dict) or not anchors.get("commit_hash"):
        return False
    days = _age_days(item.get("created_at"), now=now)
    return days is not None and days >= age_days


def normalize_search_result(item: Any) -> dict:
    """검색 결과(SearchResult 객체 또는 surface dict)를 포맷터 소비용 dict로 정규화.

    두 훅의 입력 타입이 다르다: user_prompt_submit은 ``SearchResult`` 객체를,
    session_start은 :func:`surface_relevant_memories` 가 만든 dict를 넘긴다.
    포맷터가 단일 스키마만 다루도록 여기서 흡수한다.
    """
    if isinstance(item, dict):

        def _get(key: str, default: Any = None) -> Any:
            return item.get(key, default)

    else:

        def _get(key: str, default: Any = None) -> Any:
            return getattr(item, key, default)

    score = _get("similarity_score", _get("score", 0.0)) or 0.0
    return {
        "id": _get("id"),
        "category": _get("category"),
        "content": _get("content", "") or "",
        "created_at": str(_get("created_at", "") or ""),
        "score": float(score),
        "title": _get("title"),
        "abstract": _get("abstract"),
        # anchors(표시·수명 판단)와 stale_status(클라이언트 검증)는 aged 경고에 쓴다.
        # 입력 타입에 따라 없을 수 있고, render 경로의 attach_stale이 DB값으로 채운다.
        "anchors": _get("anchors"),
        "stale_status": _get("stale_status"),
    }


def format_memory_lines(
    memories: List[dict],
    *,
    content_limit: int = _SUMMARY_LIMIT,
    now: Optional[datetime] = None,
    aged_days: Optional[int] = None,
) -> List[str]:
    """정규화된 메모리 dict 목록을 주입용 bullet 라인으로 변환(공유 포맷터).

    포맷: ``- [category] (나이 · 출처[ · 미검증 anchor]) title — abstract요약``. LLM
    호출 없이 저장된 데이터와 순수 파싱만으로 3단 fallback을 적용한다(모듈 상단 주석
    참조). 오래된 미검증 commit_hash 앵커를 가진 메모리는 meta에 ``· 미검증 anchor``
    경고 토큰을 덧붙인다(제외는 하지 않음 — 제외는 선별 단계 filter_injectable 책임).
    헤더 라인("## Related Memories" 등)은 각 훅이 소유하므로 여기서는 붙이지 않는다.

    Args:
        content_limit: 요약/자유 텍스트 길이 상한(문장 경계 우선).
        now: 나이 계산 기준 시각(테스트용). None이면 ``datetime.now()``.
        aged_days: aged-anchor 임계(일). None이면 설정값(기본 90).
    """
    threshold = aged_days if aged_days is not None else _aged_anchor_age_days()
    lines: List[str] = []
    for m in memories:
        cat = m.get("category") or "unknown"
        title_e = (m.get("title") or "").strip()
        if title_e:
            # Tier 1: enrichment title/abstract 사용.
            title = _cap(title_e, _TITLE_LIMIT)
            abstract = m.get("abstract") or ""
            summary = _clip(abstract, content_limit) if abstract.strip() else ""
            source = "enriched"
        else:
            # Tier 2/3: 원문 파싱.
            title, summary, source = _derive_from_content(
                m.get("content") or "",
                title_limit=_TITLE_LIMIT,
                summary_limit=content_limit,
            )
        age = _relative_age(m.get("created_at"), now=now)
        parts = [p for p in (age, source) if p]
        if _is_aged_anchor(m, now=now, age_days=threshold):
            parts.append(_AGED_ANCHOR_TOKEN)
        meta = " · ".join(parts)
        body = f"{title} — {summary}" if summary else title
        lines.append(f"- [{cat}] ({meta}) {body}")
    return lines


async def _enrichment_table_exists(db: Any) -> bool:
    """memory_enrichment 존재 여부를 순수 read로 확인(lazy 테이블 가드).

    enrichment는 lazy-created side 테이블이라 enrichment를 한 번도 돌리지 않은 DB엔
    없을 수 있다. read-only surfacing 경로에서 테이블을 만드는 쓰기 부작용을 피하려고
    ``ensure_schema`` 대신 sqlite_master를 조회한다(memory.py의 동일 패턴).
    """
    try:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (_ENRICHMENT_TABLE,),
        )
        return cursor.fetchone() is not None
    except Exception as e:  # noqa: BLE001 — best-effort guard, never break caller
        logger.debug(f"enrichment table check failed: {e}")
        return False


async def fetch_enrichment_map(db: Any, memory_ids: Any) -> dict:
    """memory_id → {'title','abstract','tags','display_kind'} 를 IN 배치로 1회 조회.

    검색 경로(search.py)는 건드리지 않고, 결과 id 목록만으로 enrichment를 병합하기
    위한 단일 배치 쿼리. db/None·빈 목록·테이블 부재는 모두 빈 dict로 graceful.
    (title/abstract만 쓰는 기존 호출부는 추가 키를 무시하므로 하위호환.)
    """
    if db is None:
        return {}
    ids = [str(i) for i in memory_ids if i]
    if not ids:
        return {}
    if not await _enrichment_table_exists(db):
        return {}
    placeholders = ",".join("?" for _ in ids)
    try:
        rows = await db.fetchall(
            f"SELECT memory_id, title, abstract, tags, display_kind "
            f"FROM {_ENRICHMENT_TABLE} WHERE memory_id IN ({placeholders})",
            tuple(ids),
        )
    except Exception as e:  # noqa: BLE001 — best-effort, never break surfacing
        logger.debug(f"enrichment batch fetch failed: {e}")
        return {}

    def _tags(raw: Any) -> list:
        try:
            parsed = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            return []
        return [str(t) for t in parsed] if isinstance(parsed, list) else []

    return {
        str(row["memory_id"]): {
            "title": row["title"],
            "abstract": row["abstract"],
            "tags": _tags(row["tags"] if "tags" in row.keys() else None),
            "display_kind": (
                row["display_kind"] if "display_kind" in row.keys() else None
            ),
        }
        for row in rows
    }


async def fetch_tag_facets(
    db: Any,
    project_id: Optional[str] = None,
    limit: int = 30,
    include_source: bool = True,
) -> List[dict]:
    """Top topic tags with counts for facet navigation: ``[{'tag','count'}]``.

    Aggregates enrichment topic tags (``memory_enrichment.tags``), optionally
    unioned with source tags (``memories.tags``), scoped to ``project_id``.
    UNION dedupes per (memory, tag) so a tag present in both sources counts once
    per memory. Graceful: missing enrichment table / JSON1 issues → source-only
    (or empty) rather than raising.
    """
    if db is None:
        return []
    limit = max(1, min(int(limit or 30), 200))
    where = "WHERE je.value IS NOT NULL AND je.value != ''"
    params: list = []
    proj = "" if not project_id else " AND m.project_id = ?"
    src_select = (
        f"SELECT je.value AS tag, m.id AS mid "
        f"FROM memories m, json_each(m.tags) je {where}{proj}"
    )
    if project_id:
        params.append(project_id)

    selects = []
    if include_source:
        selects.append(src_select)
    if await _enrichment_table_exists(db):
        enr_select = (
            f"SELECT je.value AS tag, m.id AS mid "
            f"FROM memory_enrichment e JOIN memories m ON m.id = e.memory_id, "
            f"json_each(e.tags) je {where}{proj}"
        )
        selects.append(enr_select)
        if project_id:
            params.append(project_id)
    if not selects:
        return []

    union = " UNION ".join(selects)
    sql = (
        f"SELECT tag, COUNT(*) AS count FROM ({union}) "
        f"GROUP BY tag ORDER BY count DESC, tag ASC LIMIT {limit}"
    )
    try:
        rows = await db.fetchall(sql, tuple(params))
    except Exception as e:  # noqa: BLE001 — facet is best-effort, never break UI
        logger.debug(f"tag facet fetch failed: {e}")
        return []
    return [{"tag": str(row["tag"]), "count": int(row["count"])} for row in rows]


_CURATABLE_CATEGORIES = (
    "decision",
    "bug",
    "incident",
    "idea",
    "code_snippet",
    "task",
)


async def fetch_curation_candidates(
    db: Any,
    project_id: Optional[str] = None,
    limit: int = 50,
    confidence_threshold: float = 0.5,
) -> List[dict]:
    """Memories worth a curation look, from enrichment signals:
    ``[{'id','category','display_kind','confidence','title','reasons'}]``.

    Flags (a) a display_kind that is a real category but disagrees with the
    stored category (likely miscategorized), and (b) low enrichment confidence
    (vague/partial). Graceful when enrichment never ran. confidence/lesson only
    exist for memories enriched after that field was added — older rows read
    NULL until re-enriched.
    """
    if db is None or not await _enrichment_table_exists(db):
        return []
    limit = max(1, min(int(limit or 50), 200))
    cats = ",".join("?" for _ in _CURATABLE_CATEGORIES)
    proj = " AND m.project_id = ?" if project_id else ""
    params: list = []
    if project_id:
        params.append(project_id)
    params.extend(_CURATABLE_CATEGORIES)
    params.append(confidence_threshold)
    sql = f"""
        SELECT m.id AS id, m.category AS category, e.display_kind AS display_kind,
               e.confidence AS confidence, e.title AS title
        FROM memory_enrichment e JOIN memories m ON m.id = e.memory_id
        WHERE COALESCE(m.status, 'canonical') = 'canonical'{proj}
          AND (
            (e.display_kind IN ({cats}) AND e.display_kind != m.category)
            OR (e.confidence IS NOT NULL AND e.confidence < ?)
          )
        ORDER BY (e.confidence IS NULL), e.confidence ASC, m.id
        LIMIT {limit}
    """
    try:
        rows = await db.fetchall(sql, tuple(params))
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.debug(f"curation candidates fetch failed: {e}")
        return []
    out = []
    for r in rows:
        dk = r["display_kind"]
        conf = r["confidence"]
        reasons = []
        if dk and dk in _CURATABLE_CATEGORIES and dk != r["category"]:
            reasons.append("miscategorized")
        if conf is not None and conf < confidence_threshold:
            reasons.append("low_confidence")
        out.append(
            {
                "id": str(r["id"]),
                "category": r["category"],
                "display_kind": dk,
                "confidence": conf,
                "title": r["title"],
                "reasons": reasons,
            }
        )
    return out


async def fetch_lessons(
    db: Any, project_id: Optional[str] = None, limit: int = 50
) -> List[dict]:
    """Reusable takeaways captured by enrichment: ``[{'id','category','title',
    'lesson'}]``. lesson is only populated for memories enriched after the field
    was added; older rows are absent until re-enriched. Graceful when no table."""
    if db is None or not await _enrichment_table_exists(db):
        return []
    limit = max(1, min(int(limit or 50), 200))
    proj = " AND m.project_id = ?" if project_id else ""
    params: list = [project_id] if project_id else []
    sql = f"""
        SELECT m.id AS id, m.category AS category, e.title AS title,
               e.lesson AS lesson
        FROM memory_enrichment e JOIN memories m ON m.id = e.memory_id
        WHERE COALESCE(m.status, 'canonical') = 'canonical'{proj}
          AND e.lesson IS NOT NULL AND e.lesson != ''
        ORDER BY m.updated_at DESC, m.id
        LIMIT {limit}
    """
    try:
        rows = await db.fetchall(sql, tuple(params))
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.debug(f"lessons fetch failed: {e}")
        return []
    return [
        {
            "id": str(r["id"]),
            "category": r["category"],
            "title": r["title"],
            "lesson": r["lesson"],
        }
        for r in rows
    ]


async def attach_enrichment(db: Any, memories: List[dict]) -> List[dict]:
    """정규화된 dict 목록에 enrichment(title/abstract)를 배치 병합(in-place).

    이미 값이 있는 필드(예: hub 결과의 title/abstract)는 보존하고, 비어 있을 때만
    로컬 enrichment로 채운다.
    """
    emap = await fetch_enrichment_map(
        db, [m.get("id") for m in memories if m.get("id")]
    )
    if not emap:
        return memories
    for m in memories:
        enr = emap.get(str(m.get("id")))
        if not enr:
            continue
        if not m.get("title") and enr.get("title"):
            m["title"] = enr["title"]
        if not m.get("abstract") and enr.get("abstract"):
            m["abstract"] = enr["abstract"]
    return memories


async def fetch_stale_map(db: Any, memory_ids: Any) -> dict:
    """memory_id → {'stale_status','anchors','created_at'} 를 IN 배치로 1회 조회.

    stale 판정(주입 제외)과 aged 경고(anchor+나이) 둘 다에 필요한 필드를 한 쿼리로
    가져온다. anchors는 저장된 JSON 문자열이므로 dict로 파싱한다. db/None·빈 목록·
    구버전 스키마(stale 컬럼 부재)는 모두 빈 dict로 graceful — 주입을 깨지 않는다.
    """
    if db is None:
        return {}
    ids = [str(i) for i in memory_ids if i]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    try:
        rows = await db.fetchall(
            f"SELECT id, stale_status, anchors, created_at FROM memories "
            f"WHERE id IN ({placeholders})",
            tuple(ids),
        )
    except Exception as e:  # noqa: BLE001 — best-effort, never break injection
        logger.debug(f"stale batch fetch failed: {e}")
        return {}
    out: dict = {}
    for row in rows:
        anchors = row["anchors"]
        if isinstance(anchors, str) and anchors:
            try:
                anchors = json.loads(anchors)
            except (ValueError, TypeError):
                anchors = None
        elif not isinstance(anchors, dict):
            anchors = None
        out[str(row["id"])] = {
            "stale_status": row["stale_status"],
            "anchors": anchors,
            "created_at": row["created_at"],
        }
    return out


async def _stale_id_set(db: Any, memory_ids: Any) -> Set[str]:
    """클라이언트가 stale로 보고한 memory_id 집합(주입 제외 대상). best-effort."""
    smap = await fetch_stale_map(db, memory_ids)
    return {
        mid
        for mid, info in smap.items()
        if info.get("stale_status") == _STALE_STATUS_STALE
    }


async def filter_injectable(db: Any, items: List[Any]) -> List[Any]:
    """주입 선별 단계: 클라이언트가 stale로 검증한 메모리를 제외한다.

    items의 원본 타입(SearchResult 객체 / surface dict)을 보존한 채 stale id만
    걸러낸다 — 호출측이 같은 리스트로 render와 record_injected를 모두 수행해 주입/
    기록의 1:1 매핑이 유지되도록. best-effort: 조회 실패·db None이면 원본 그대로.
    """
    if not items:
        return items

    def _id(it: Any) -> Optional[str]:
        rid = it.get("id") if isinstance(it, dict) else getattr(it, "id", None)
        return str(rid) if rid is not None else None

    stale = await _stale_id_set(db, [_id(it) for it in items])
    if not stale:
        return items
    return [it for it in items if _id(it) not in stale]


async def attach_stale(db: Any, memories: List[dict]) -> List[dict]:
    """정규화 dict에 stale_status/anchors/created_at을 DB 권위값으로 병합(in-place).

    aged 경고(commit_hash 앵커 + 나이) 판단에 필요한 필드를 채운다. surface dict는
    anchors를 싣지 않고 SearchResult는 stale_status를 싣지 않으므로 DB가 단일 진실:
    stale_status는 항상 DB값으로 덮어쓰고, anchors/created_at은 비어 있을 때만 채운다.
    """
    smap = await fetch_stale_map(db, [m.get("id") for m in memories if m.get("id")])
    if not smap:
        return memories
    for m in memories:
        info = smap.get(str(m.get("id")))
        if not info:
            continue
        m["stale_status"] = info.get("stale_status")
        if not m.get("anchors") and info.get("anchors"):
            m["anchors"] = info["anchors"]
        if not m.get("created_at") and info.get("created_at"):
            m["created_at"] = info["created_at"]
    return memories


async def render_memory_lines(
    db: Any,
    items: List[Any],
    *,
    content_limit: int = _SUMMARY_LIMIT,
    now: Optional[datetime] = None,
) -> List[str]:
    """두 훅 공통 경로: 정규화 → enrichment + stale 배치 병합 → 공유 포맷.

    호출측이 이미 선별한(카테고리/threshold/limit, 그리고 stale 제외) 결과 목록을
    받아 주입 bullet 라인으로 렌더한다. stale 제외(주입 배제)는 선별 단계
    (:func:`filter_injectable` / :func:`surface_relevant_memories`) 책임이고, 여기서는
    aged 경고 표기를 위해 anchors/stale_status만 DB에서 채워 포맷에 넘긴다.
    """
    normalized = [normalize_search_result(it) for it in items]
    await attach_enrichment(db, normalized)
    await attach_stale(db, normalized)
    return format_memory_lines(normalized, content_limit=content_limit, now=now)
