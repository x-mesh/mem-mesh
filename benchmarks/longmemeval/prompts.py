"""Prompt templates for LongMemEval benchmark.

Judge prompts are from the official LongMemEval evaluation:
https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py
"""

# ---------------------------------------------------------------------------
# Judge prompts (5 types)
# ---------------------------------------------------------------------------

JUDGE_STANDARD = """\
I will give you a question, a correct answer, and a response from a model. \
Please answer yes if the response contains the correct answer. Otherwise, answer no. \
If the response is equivalent to the correct answer or contains all the intermediate \
steps to get the correct answer, you should also answer yes. If the response only \
contains a subset of the information required by the answer, answer no.

Question: {question}

Correct Answer: {answer}

Model Response: {response}

Is the model response correct? Answer yes or no only."""

JUDGE_TEMPORAL = """\
I will give you a question, a correct answer, and a response from a model. \
Please answer yes if the response contains the correct answer. Otherwise, answer no. \
If the response is equivalent to the correct answer or contains all the intermediate \
steps to get the correct answer, you should also answer yes. If the response only \
contains a subset of the information required by the answer, answer no.

In addition, do not penalize off-by-one errors for the number of days. \
If the question asks for the number of days/weeks/months, etc., and the model \
makes off-by-one errors (e.g., predicting 19 days when the answer is 18), \
the model's response is still correct.

Question: {question}

Correct Answer: {answer}

Model Response: {response}

Is the model response correct? Answer yes or no only."""

JUDGE_KNOWLEDGE_UPDATE = """\
I will give you a question, a correct answer, and a response from a model. \
Please answer yes if the response contains the correct answer. Otherwise, answer no. \
If the response contains some previous information along with an updated answer, \
the response should be considered as correct as long as the updated answer is \
the required answer.

Question: {question}

Correct Answer: {answer}

Model Response: {response}

Is the model response correct? Answer yes or no only."""

JUDGE_PREFERENCE = """\
I will give you a question, a rubric for desired personalized response, and a \
response from a model. Please answer yes if the response satisfies the desired \
response. Otherwise, answer no. The model does not need to reflect all the points \
in the rubric. The response is correct as long as it recalls and utilizes the \
user's personal information correctly.

Question: {question}

Rubric: {answer}

Model Response: {response}

Is the model response correct? Answer yes or no only."""

JUDGE_ABSTENTION = """\
I will give you an unanswerable question, an explanation, and a response from \
a model. Please answer yes if the model correctly identifies the question as \
unanswerable. The model could say that the information is incomplete, or some \
other information is given but the asked information is not.

Question: {question}

Explanation: {answer}

Model Response: {response}

Does the model correctly identify the question as unanswerable? Answer yes or no only."""


def get_judge_prompt(
    question_id: str,
    question_type: str,
    question: str,
    answer: str,
    response: str,
) -> str:
    """Select and format the appropriate judge prompt."""
    fmt = dict(question=question, answer=answer, response=response)

    # Abstention questions take priority (identified by _abs suffix)
    if "_abs" in question_id:
        return JUDGE_ABSTENTION.format(**fmt)

    prompt_map = {
        "single-session-user": JUDGE_STANDARD,
        "single-session-assistant": JUDGE_STANDARD,
        "multi-session": JUDGE_STANDARD,
        "temporal-reasoning": JUDGE_TEMPORAL,
        "knowledge-update": JUDGE_KNOWLEDGE_UPDATE,
        "single-session-preference": JUDGE_PREFERENCE,
    }
    template = prompt_map.get(question_type, JUDGE_STANDARD)
    return template.format(**fmt)


# ---------------------------------------------------------------------------
# Answer generation prompts
# ---------------------------------------------------------------------------

GENERATION_DIRECT = """\
You are a helpful assistant with access to past conversation history. \
Use the retrieved conversation excerpts below to answer the user's question. \
If the information is not available in the provided context, say so clearly.

Important: Excerpts are ordered chronologically (oldest first, newest last). \
If the same topic appears in multiple excerpts, always prefer the MOST RECENT information. \
When a user updates a preference, status, or fact, the latest mention supersedes all earlier ones.

Today's date: {question_date}

=== Retrieved Conversations ===
{context}
=== End of Retrieved Conversations ===

Question: {question}

Answer concisely and directly based on the most up-to-date information above."""

GENERATION_COT = """\
You are a helpful assistant with access to past conversation history. \
Use the retrieved conversation excerpts below to answer the user's question. \
If the information is not available in the provided context, say so clearly.

Important: Excerpts are ordered chronologically (oldest first, newest last). \
If the same topic appears in multiple excerpts, always prefer the MOST RECENT information. \
When a user updates a preference, status, or fact, the latest mention supersedes all earlier ones.

Today's date: {question_date}

=== Retrieved Conversations ===
{context}
=== End of Retrieved Conversations ===

Question: {question}

Think step by step:
1. Identify which excerpts are relevant to the question.
2. If multiple excerpts discuss the same topic, note the dates and prefer the newest.
3. For preference or knowledge-update questions, the latest information takes priority.
Then provide your final answer after "ANSWER:"."""


def get_generation_prompt(
    question: str,
    question_date: str,
    context: str,
    use_cot: bool = False,
) -> str:
    """Format the answer generation prompt."""
    template = GENERATION_COT if use_cot else GENERATION_DIRECT
    return template.format(
        question=question,
        question_date=question_date,
        context=context,
    )
