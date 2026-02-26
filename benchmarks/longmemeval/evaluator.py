"""GPT-4o judge 평가 (LongMemEval 논문 기반)"""

import logging
from typing import Optional

from .config import EvaluationConfig

logger = logging.getLogger(__name__)

# LongMemEval 논문의 평가 프롬프트 (question_type별 특화)
EVAL_SYSTEM_PROMPT = """You are an impartial judge evaluating the quality of an AI assistant's answer to a question about past conversations.
You will be given the ground truth answer and the AI's hypothesis answer.
Your task is to determine if the hypothesis answer is correct.

Output ONLY a single number:
1 if the hypothesis is correct (matches the ground truth in meaning)
0 if the hypothesis is incorrect"""

EVAL_USER_TEMPLATE = """## Question Type
{question_type}

## Question
{question}

## Ground Truth Answer
{ground_truth}

## AI's Hypothesis Answer
{hypothesis}

## Evaluation Criteria
- For factual questions: The hypothesis must contain the key facts from the ground truth.
- For temporal questions: Dates and time references must be accurate.
- For multi-session questions: All relevant pieces of information must be present.
- Minor wording differences are acceptable if the meaning is preserved.
- Partial answers should be marked as 0 (incorrect) unless they contain the essential information.

## Your Judgment (0 or 1):"""

# 기권(abstention) 유형: hypothesis가 "모른다"면 정답
ABSTENTION_KEYWORDS = [
    "i don't know",
    "i cannot answer",
    "i'm not sure",
    "insufficient information",
    "no information available",
    "cannot determine",
    "unable to answer",
    "모르겠",
    "답할 수 없",
    "알 수 없",
    "정보가 부족",
    "확인할 수 없",
]


def is_abstention_type(question_type: str) -> bool:
    """기권 유형 질문인지 확인"""
    return question_type.endswith("_abs")


def is_abstention_answer(hypothesis: str) -> bool:
    """hypothesis가 기권 답변인지 확인"""
    hypothesis_lower = hypothesis.lower()
    return any(kw in hypothesis_lower for kw in ABSTENTION_KEYWORDS)


async def evaluate_answer(
    question: str,
    question_type: str,
    ground_truth: str,
    hypothesis: str,
    config: EvaluationConfig,
) -> Optional[int]:
    """GPT-4o judge로 답변 평가

    Args:
        question: 질문 텍스트
        question_type: 질문 유형
        ground_truth: 정답
        hypothesis: LLM 생성 답변
        config: 평가 설정

    Returns:
        0 (오답) 또는 1 (정답), 실패 시 None
    """
    # 기권 유형 처리: hypothesis가 "모른다"면 정답
    if is_abstention_type(question_type):
        if is_abstention_answer(hypothesis):
            return 1
        # 기권 유형인데 답변을 했으면 judge로 평가
        # (실제로 맞을 수도 있으므로)

    try:
        import litellm
    except ImportError:
        raise ImportError(
            "litellm 패키지가 필요합니다: pip install litellm"
        )

    user_prompt = EVAL_USER_TEMPLATE.format(
        question_type=question_type,
        question=question,
        ground_truth=ground_truth,
        hypothesis=hypothesis,
    )

    try:
        response = await litellm.acompletion(
            model=config.judge_model,
            messages=[
                {"role": "system", "content": EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=config.temperature,
            max_tokens=5,
        )
        result_text = response.choices[0].message.content.strip()

        # "0" 또는 "1" 파싱
        if "1" in result_text:
            return 1
        elif "0" in result_text:
            return 0
        else:
            logger.warning(
                f"Unexpected judge response: {result_text}"
            )
            return None
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        return None
