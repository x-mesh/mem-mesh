"""Parallel benchmark worker — processes a subset of questions independently.

Usage:
    python benchmarks/longmemeval/worker.py --group-file /tmp/bench_group_1.json --worker-id 1
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.longmemeval.config import BenchmarkConfig
from benchmarks.longmemeval.dataset import download_dataset, load_questions
from benchmarks.longmemeval.indexer import index_question
from benchmarks.longmemeval.retriever import retrieve_for_question
from benchmarks.longmemeval.generator import generate_answer
from benchmarks.longmemeval.evaluator import evaluate_answer

logger = logging.getLogger(__name__)


async def process_one(question, embedding_service, config):
    """Process a single question, return result dict."""
    start = time.time()
    await index_question(question, embedding_service, config)
    retrieval = await retrieve_for_question(question, embedding_service, config)
    generated_answer, gen_time = generate_answer(question, retrieval, config)
    is_correct, judge_response, eval_time = evaluate_answer(
        question, generated_answer, config
    )
    total_time = time.time() - start
    return {
        "question_id": question.question_id,
        "question_type": question.question_type,
        "is_abstention": question.is_abstention,
        "retrieved_session_ids": retrieval.retrieved_session_ids,
        "recall_any": retrieval.recall_any,
        "recall_all": retrieval.recall_all,
        "search_time_ms": retrieval.search_time_ms,
        "generated_answer": generated_answer,
        "generation_time_s": gen_time,
        "is_correct": is_correct,
        "judge_response": judge_response,
        "eval_time_s": eval_time,
        "total_time_s": total_time,
    }


async def run_worker(group_file: str, worker_id: int, topk: int, enable_reranking: bool):
    """Run benchmark on a subset of questions."""
    question_ids = json.load(open(group_file))
    output_file = f"/tmp/bench_result_{worker_id}.json"

    config = BenchmarkConfig(
        variant="s",
        topk=topk,
        search_mode="hybrid",
        enable_reranking=enable_reranking,
    )

    download_dataset(config)
    all_questions = load_questions(config)
    target_set = set(question_ids)
    questions = [q for q in all_questions if q.question_id in target_set]

    from app.core.embeddings.service import EmbeddingService
    embedding_service = EmbeddingService(preload=True)

    results = []
    correct = 0
    for i, q in enumerate(questions, 1):
        try:
            result = await process_one(q, embedding_service, config)
            results.append(result)
            if result["is_correct"]:
                correct += 1
            status = "OK" if result["is_correct"] else "WRONG"
            print(
                f"[W{worker_id}] [{i}/{len(questions)}] {q.question_id} "
                f"({q.question_type}) {status} "
                f"recall={result['recall_any']:.0f} "
                f"gen={result['generation_time_s']:.1f}s "
                f"[{correct}/{i}={correct/i:.0%}]",
                flush=True,
            )
        except Exception as e:
            print(f"[W{worker_id}] [{i}/{len(questions)}] {q.question_id} ERROR: {e}", flush=True)
            results.append({
                "question_id": q.question_id,
                "question_type": q.question_type,
                "is_abstention": q.is_abstention,
                "retrieved_session_ids": [],
                "recall_any": 0,
                "recall_all": 0,
                "search_time_ms": 0,
                "generated_answer": f"(worker error: {e})",
                "generation_time_s": 0,
                "is_correct": False,
                "judge_response": "",
                "eval_time_s": 0,
                "total_time_s": 0,
            })

        # Save incrementally
        json.dump(results, open(output_file, "w"), ensure_ascii=False, indent=2)

    print(f"\n[W{worker_id}] Done: {correct}/{len(questions)} ({correct/max(len(questions),1):.0%})", flush=True)
    return results


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--group-file", required=True)
    parser.add_argument("--worker-id", type=int, required=True)
    parser.add_argument("--topk", type=int, default=15)
    parser.add_argument("--enable-reranking", action="store_true")
    args = parser.parse_args()

    asyncio.run(run_worker(args.group_file, args.worker_id, args.topk, args.enable_reranking))


if __name__ == "__main__":
    main()
