"""Evaluate the configured Reconciler judge on fixed synthetic evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.core.database.base import Database
from app.core.services.llm_resolver import resolve_service_llm
from app.core.services.memory_reconciler import (
    MAX_EVIDENCE_CHARS,
    PROMPT_VERSION,
    MemoryReconcilerService,
    is_external_llm_endpoint,
)
from app.core.services.relay_worker import build_relay_enricher


class Evidence(BaseModel):
    memory_id: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=MAX_EVIDENCE_CHARS)
    metadata: dict[str, str] = Field(default_factory=dict)


class JudgeCase(BaseModel):
    id: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1, max_length=12)
    expected_actions: list[str] = Field(min_length=1)
    expected_review_reason: Optional[str] = None
    required_terms: list[str] = Field(default_factory=list)
    required_source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bound_evidence(self):
        if (
            len(
                json.dumps(
                    [item.model_dump() for item in self.evidence], ensure_ascii=False
                )
            )
            > MAX_EVIDENCE_CHARS
        ):
            raise ValueError("case evidence exceeds the Reconciler input budget")
        return self


class JudgeSuite(BaseModel):
    cases: list[JudgeCase] = Field(min_length=1, max_length=20)


async def evaluate_cases(judge: Any, cases: list[JudgeCase]) -> dict:
    validator = MemoryReconcilerService(None)
    results = []
    for case in cases:
        evidence = [item.model_dump() for item in case.evidence]
        failures = []
        action = None
        review_reason = None
        try:
            payload = await judge.reconcile_group(evidence)
            decision = validator._normalize_payload(payload, evidence)
            action = decision["action"]
            review_reason = decision.get("review_reason")
            if action not in case.expected_actions:
                failures.append("unexpected action")
            if (
                case.expected_review_reason is not None
                and review_reason != case.expected_review_reason
            ):
                failures.append("unexpected review reason")
            body = str(decision.get("body") or "").casefold()
            for term in case.required_terms:
                if term.casefold() not in body:
                    failures.append(f"missing term: {term}")
            for term in case.required_terms:
                supporting_claims = [
                    claim
                    for claim in decision.get("claims") or []
                    if term.casefold() in claim.get("text", "").casefold()
                    and claim.get("source_refs")
                ]
                if not supporting_claims:
                    failures.append(f"uncited term: {term}")
            cited = {
                ref["memory_id"]
                for claim in decision.get("claims") or []
                for ref in claim.get("source_refs") or []
            }
            for memory_id in case.required_source_ids:
                if memory_id not in cited:
                    failures.append(f"missing source: {memory_id}")
        except Exception as exc:
            failures.append(f"judge or schema error: {type(exc).__name__}")
        results.append(
            {
                "id": case.id,
                "action": action,
                "review_reason": review_reason,
                "passed": not failures,
                "failures": failures,
            }
        )
    return {
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "cases": results,
    }


async def _run(database_path: str, project_id: str, suite: JudgeSuite) -> dict:
    settings = get_settings()
    db = Database(database_path, embedding_dim=settings.embedding_dim)
    await db.connect()
    try:
        config = await resolve_service_llm(db, settings, "reconcile")
        if not config["api_key"] or not config["model"]:
            raise ValueError("reconciler LLM is not configured")
        policy = await MemoryReconcilerService(db).get_policy(project_id)
        if (
            is_external_llm_endpoint(config["base_url"])
            and not policy["allow_external_llm"]
        ):
            raise ValueError("external LLM is not allowed for this project")
        judge = build_relay_enricher(
            provider=config["provider"],
            api_key=config["api_key"],
            model=config["model"],
            base_url=config["base_url"],
            timeout=settings.relay_llm_timeout,
        )
        report = await evaluate_cases(judge, suite.cases)
        report.update(
            {
                "project_id": project_id,
                "model": config["model"],
                "prompt_version": PROMPT_VERSION,
                "fixture_sha256": hashlib.sha256(
                    suite.model_dump_json().encode("utf-8")
                ).hexdigest(),
            }
        )
        return report
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--cases", required=True)
    args = parser.parse_args()
    suite = JudgeSuite.model_validate_json(Path(args.cases).read_text())
    report = asyncio.run(_run(args.database, args.project, suite))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
