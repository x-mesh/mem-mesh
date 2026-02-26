"""LLM 답변 생성 (litellm 기반)"""

import logging
from typing import List, Optional

from app.core.schemas.responses import SearchResult

from .config import GenerationConfig

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on the provided conversation history.
Answer the question using ONLY the information from the provided context.
If the context does not contain enough information to answer, say "I don't know" or "I cannot answer based on the available information."
Be concise and direct in your answer."""

USER_PROMPT_TEMPLATE = """Based on the following conversation history, answer the question.

## Conversation History
{context}

## Question
{question}

{date_context}

## Answer"""


def build_context(results: List[SearchResult]) -> str:
    """검색 결과를 LLM 입력 컨텍스트로 변환"""
    parts: List[str] = []
    for i, result in enumerate(results):
        parts.append(f"--- Context {i + 1} (score: {result.similarity_score:.3f}) ---")
        parts.append(result.content)
        parts.append("")
    return "\n".join(parts)


async def generate_answer(
    question: str,
    results: List[SearchResult],
    config: GenerationConfig,
    question_date: Optional[str] = None,
) -> str:
    """LLM을 사용하여 답변 생성

    Args:
        question: 질문 텍스트
        results: 검색 결과
        config: 생성 설정
        question_date: 질문 시점 날짜

    Returns:
        생성된 답변
    """
    try:
        import litellm
    except ImportError:
        raise ImportError(
            "litellm 패키지가 필요합니다: pip install litellm"
        )

    context = build_context(results)
    date_context = (
        f"Note: The question is being asked on {question_date}."
        if question_date
        else ""
    )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        context=context,
        question=question,
        date_context=date_context,
    )

    try:
        response = await litellm.acompletion(
            model=config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        answer = response.choices[0].message.content.strip()
        return answer
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        raise
