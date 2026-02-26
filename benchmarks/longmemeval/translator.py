"""한국어 번역 파이프라인

3단계 번역:
  Phase 1: questions + answers (500쌍)
  Phase 2: answer_sessions (증거 세션만)
  Phase 3: 전체 haystack (선택)
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import BenchmarkConfig
from .dataset import load_dataset
from .models import BenchmarkItem

logger = logging.getLogger(__name__)

TRANSLATION_SYSTEM_PROMPT = """You are a professional Korean translator specializing in natural conversational Korean.

Rules:
1. Translate to natural conversational Korean (NOT 번역투/translationese).
2. Proper nouns: Keep original or transliterate (Alice → 앨리스).
3. Dates/numbers: Keep original format.
4. Entity consistency: Same name must be translated identically throughout.
5. Preserve the structure and meaning exactly.
6. Do NOT add explanations or notes."""

TRANSLATE_QA_PROMPT = """Translate the following question and answer pair into Korean.
Return ONLY a JSON object with "question" and "answer" keys.

Question: {question}
Answer: {answer}

Output (JSON only):"""

TRANSLATE_SESSION_PROMPT = """Translate the following conversation session into Korean.
Return ONLY a JSON array of strings (each string is one utterance).

Session:
{session}

Output (JSON array only):"""


async def translate_dataset(
    config: BenchmarkConfig,
    phase: int = 1,
    output_path: Optional[str] = None,
) -> None:
    """데이터셋 한국어 번역

    Args:
        config: 벤치마크 설정
        phase: 번역 단계 (1=QA, 2=증거 세션, 3=전체 haystack)
        output_path: 출력 파일 경로
    """
    try:
        import litellm
    except ImportError:
        raise ImportError(
            "litellm 패키지가 필요합니다: pip install litellm"
        )

    # 영문 데이터 로드
    en_config = BenchmarkConfig(**config.model_dump())
    en_config.dataset.language = "en"
    items = load_dataset(en_config)

    if output_path is None:
        output_path = str(
            Path(__file__).parent / "data" / "longmemeval_ko.json"
        )

    # 기존 번역 결과 로드 (이어하기)
    existing = _load_existing(output_path)
    translated_ids = {item["question_id"] for item in existing}

    logger.info(
        f"Phase {phase} translation: {len(items)} items, "
        f"{len(translated_ids)} already translated"
    )

    results = list(existing)

    for i, item in enumerate(items):
        if item.question_id in translated_ids:
            continue

        try:
            translated = await _translate_item(
                item, phase, config.generation.model
            )
            results.append(translated)
            translated_ids.add(item.question_id)

            # 주기적 저장
            if (i + 1) % 10 == 0:
                _save_results(results, output_path)
                logger.info(f"Progress: {len(translated_ids)}/{len(items)}")

        except Exception as e:
            logger.error(
                f"Translation failed for {item.question_id}: {e}"
            )
            continue

    _save_results(results, output_path)
    logger.info(
        f"Translation complete: {len(results)} items saved to {output_path}"
    )


async def _translate_item(
    item: BenchmarkItem,
    phase: int,
    model: str,
) -> Dict[str, Any]:
    """단일 항목 번역"""
    import litellm

    result = item.model_dump()

    # Phase 1: question + answer
    qa_prompt = TRANSLATE_QA_PROMPT.format(
        question=item.question, answer=item.answer
    )
    qa_response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {"role": "user", "content": qa_prompt},
        ],
        temperature=0.1,
        max_tokens=512,
    )
    qa_text = qa_response.choices[0].message.content.strip()
    qa_json = _parse_json(qa_text)
    if qa_json:
        result["question"] = qa_json.get("question", item.question)
        result["answer"] = qa_json.get("answer", item.answer)

    if phase < 2:
        return result

    # Phase 2: answer_sessions만 번역
    translated_sessions = list(item.haystack_sessions)
    for sid in item.answer_session_ids:
        if sid < len(item.haystack_sessions):
            session = item.haystack_sessions[sid]
            translated = await _translate_session(
                session, model
            )
            if translated:
                translated_sessions[sid] = translated

    result["haystack_sessions"] = translated_sessions

    if phase < 3:
        return result

    # Phase 3: 전체 haystack 번역
    for sid in range(len(item.haystack_sessions)):
        if sid in item.answer_session_ids:
            continue  # 이미 Phase 2에서 번역됨
        session = item.haystack_sessions[sid]
        translated = await _translate_session(session, model)
        if translated:
            translated_sessions[sid] = translated

    result["haystack_sessions"] = translated_sessions
    return result


async def _translate_session(
    session: List[str], model: str
) -> Optional[List[str]]:
    """세션 발화 리스트 번역"""
    import litellm

    session_text = "\n".join(
        f"[{i}] {utt}" for i, utt in enumerate(session)
    )
    prompt = TRANSLATE_SESSION_PROMPT.format(session=session_text)

    try:
        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        text = response.choices[0].message.content.strip()
        parsed = _parse_json(text)
        if isinstance(parsed, list):
            return parsed
        return None
    except Exception as e:
        logger.warning(f"Session translation failed: {e}")
        return None


def _parse_json(text: str) -> Any:
    """JSON 파싱 (코드 블록 제거 포함)"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse JSON: {text[:100]}...")
        return None


def _load_existing(path: str) -> List[Dict[str, Any]]:
    """기존 번역 결과 로드"""
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_results(
    results: List[Dict[str, Any]], path: str
) -> None:
    """번역 결과 저장"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
