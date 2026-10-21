"""Durable, non-destructive Memory Reconciler workflow."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit
from uuid import uuid4

import numpy as np

from app.core.redaction import redact_secrets

from ..database.base import Database, anchored_path_filter_clause
from ..errors import ReconcilerConflictError, ReconcilerValidationError
from ..schemas.reconciler import (
    RECONCILER_ACTIONS,
    ReconcilerClaim,
    ReconcilerPolicy,
    canonical_json,
    make_curated_id,
)
from ..schemas.requests import normalize_anchored_path
from .effective_read import EffectiveReadService
from .quality_gate import reconciler_evidence_exclusion

logger = logging.getLogger(__name__)

MAX_GROUP_MEMORIES = 12
MAX_PROVENANCE_SOURCES = 8
MAX_TEMPORAL_WINDOW_DAYS = 365
MAX_EVIDENCE_CHARS = 48000
MAX_ESTIMATED_INPUT_TOKENS_PER_GROUP = 12000
MAX_ESTIMATED_INPUT_TOKENS_PER_RUN = 240000
MAX_LLM_CALLS_PER_RUN = 100
MAX_ACTIVATIONS_PER_RUN = 25
MAX_RUN_SECONDS = 900
MAX_QUEUED_DETECTIONS = 8
METRIC_TREND_WINDOW_RUNS = 10
DETECTION_LEASE_SECONDS = 3600
JUDGE_REPAIR_RETRIES = 1
LEASE_SECONDS = 120
DETECTOR_VERSION = "candidate-v4"
PROMPT_VERSION = "reconciler-v9"
EVIDENCE_RETENTION_CONFIG_PREFIX = "reconciler.retain_evidence_content."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _epoch() -> float:
    return time.time()


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _redact_evidence(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redact_evidence(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_evidence(item) for key, item in value.items()}
    return value


def _tokens(value: str) -> set:
    return {part.casefold() for part in str(value or "").split() if len(part) > 2}


def _similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_external_llm_endpoint(base_url: str) -> bool:
    if not base_url:
        return True
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return True
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


class MemoryReconcilerService:
    """Run detection, judgment, approval, activation, and cancellation."""

    def __init__(
        self,
        db: Database,
        embedding_service: Any = None,
        *,
        prompt_version: str = PROMPT_VERSION,
        model: str = "",
        provider: str = "",
        llm_base_url: Optional[str] = None,
        llm_configured: Optional[bool] = None,
        lease_seconds: int = LEASE_SECONDS,
        max_attempts: int = 5,
        backoff_max_seconds: float = 3600.0,
    ):
        self.db = db
        self.embedding_service = embedding_service
        self.effective_read = EffectiveReadService(db, embedding_service)
        self.prompt_version = prompt_version
        self.model = model
        self.provider = provider.strip().lower()
        self.llm_base_url = llm_base_url
        self.llm_configured = llm_configured
        self.lease_seconds = lease_seconds
        self._legacy_service = None
        self._legacy_options = {
            "max_attempts": max_attempts,
            "backoff_max_seconds": backoff_max_seconds,
            "lease_seconds": lease_seconds,
        }

    async def _ensure_mutation_allowed(self) -> None:
        if await self.db.migration_in_progress():
            raise ReconcilerValidationError(
                "embedding migration is in progress; retry the activation after it completes"
            )

    async def _policy(self, project_id: str) -> ReconcilerPolicy:
        retained = await self.db.get_app_config(
            EVIDENCE_RETENTION_CONFIG_PREFIX + project_id
        )
        if retained not in {None, "true", "false"}:
            raise ReconcilerValidationError("invalid evidence retention policy")
        row = await self.db.fetchone(
            "SELECT auto_noise_suppression, auto_derived_relations, allow_external_llm FROM reconciler_project_policy WHERE project_id = ?",
            (project_id,),
        )
        if not row:
            return ReconcilerPolicy(retain_evidence_content=retained != "false")
        return ReconcilerPolicy(
            auto_noise_suppression=bool(row["auto_noise_suppression"]),
            auto_derived_relations=bool(row["auto_derived_relations"]),
            allow_external_llm=bool(row["allow_external_llm"]),
            retain_evidence_content=retained != "false",
        )

    async def _llm_allowed(self, project_id: str, base_url: str) -> bool:
        if not is_external_llm_endpoint(base_url):
            return True
        return (await self._policy(project_id)).allow_external_llm

    async def get_policy(self, project_id: str) -> dict:
        policy = await self._policy(project_id)
        row = await self.db.fetchone(
            "SELECT revision, updated_at FROM reconciler_project_policy WHERE project_id = ?",
            (project_id,),
        )
        value = policy.model_dump()
        value.update(
            {
                "project_id": project_id,
                "revision": int(row["revision"]) if row else 0,
                "updated_at": row["updated_at"] if row else None,
            }
        )
        return value

    async def set_policy(self, project_id: str, policy: Any) -> dict:
        if isinstance(policy, ReconcilerPolicy):
            value = policy
        else:
            value = ReconcilerPolicy.model_validate(policy)
        now = _now()
        async with self.db.transaction():
            await self.db.set_app_config(
                EVIDENCE_RETENTION_CONFIG_PREFIX + project_id,
                "true" if value.retain_evidence_content else "false",
            )
            row = await self.db.fetchone(
                "SELECT revision FROM reconciler_project_policy WHERE project_id = ?",
                (project_id,),
            )
            revision = int(row["revision"]) + 1 if row else 1
            await self.db.execute(
                "DELETE FROM reconciler_project_policy WHERE project_id = ?",
                (project_id,),
            )
            await self.db.execute(
                "INSERT INTO reconciler_project_policy(project_id, auto_noise_suppression, auto_derived_relations, allow_external_llm, revision, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    int(value.auto_noise_suppression),
                    int(value.auto_derived_relations),
                    int(value.allow_external_llm),
                    revision,
                    now,
                ),
            )
        return await self.get_policy(project_id)

    async def _snapshot_memory(
        self, row: Any, provenance: Optional[dict] = None
    ) -> dict:
        memory_id = str(row["id"])
        relations = await self.db.fetchall(
            "SELECT source_id, target_id, relation_type, strength, metadata FROM memory_relations WHERE source_id = ? OR target_id = ? ORDER BY source_id, target_id, relation_type, id",
            (memory_id, memory_id),
        )
        relation_data = [dict(item) for item in relations]
        metadata = {
            "project_id": row["project_id"],
            "category": row["category"],
            "source": row["source"],
            "client": row["client"] if "client" in row.keys() else None,
            "tags": row["tags"],
            "status": row["status"] if "status" in row.keys() else "canonical",
            "stale_status": (
                row["stale_status"] if "stale_status" in row.keys() else None
            ),
            "stale_checked_at": (
                row["stale_checked_at"] if "stale_checked_at" in row.keys() else None
            ),
            "is_starred": row["is_starred"] if "is_starred" in row.keys() else 0,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        protected = bool(
            row["reconciler_protected"]
            if "reconciler_protected" in row.keys()
            else False
        )
        if protected:
            metadata["reconciler_protected"] = True
        anchors = row["anchors"] if "anchors" in row.keys() else None
        content = str(row["content"] or "")
        excluded_reason = reconciler_evidence_exclusion(content)
        safe_content = redact_secrets(content)
        content_truncated = len(safe_content) > MAX_EVIDENCE_CHARS
        redacted_content = safe_content[:MAX_EVIDENCE_CHARS]
        title = next(
            (
                line.strip(" #").strip()
                for line in redacted_content.splitlines()
                if line.strip(" #").strip()
            ),
            "",
        )[:120]
        if excluded_reason:
            redacted_content = ""
            title = ""
        input_payload = {
            "memory_id": memory_id,
            "content": content,
            "content_hash": row["content_hash"],
            "project_id": row["project_id"],
            "category": row["category"],
            "source": row["source"],
            "client": row["client"] if "client" in row.keys() else None,
            "tags": row["tags"],
            "status": row["status"] if "status" in row.keys() else "canonical",
            "anchors": anchors,
            "is_starred": row["is_starred"] if "is_starred" in row.keys() else 0,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "relations": relation_data,
        }
        if protected:
            input_payload["reconciler_protected"] = True
        if "stale_status" in row.keys() and row["stale_status"] is not None:
            input_payload["stale_status"] = row["stale_status"]
        return {
            "memory_id": memory_id,
            "content": redacted_content,
            "content_truncated": content_truncated,
            "content_excluded_reason": excluded_reason,
            "title": title,
            "content_hash": row["content_hash"],
            "metadata": _redact_evidence(metadata),
            "anchors": _redact_evidence(anchors),
            "relations": _redact_evidence(relation_data),
            "provenance": provenance or {"pin_ids": [], "session_ids": []},
            "retrieval_stats": {
                "access_count": (
                    row["access_count"] if "access_count" in row.keys() else None
                ),
                "last_accessed_at": (
                    row["last_accessed_at"]
                    if "last_accessed_at" in row.keys()
                    else None
                ),
            },
            "input_hash": _hash(input_payload),
            "metadata_hash": _hash(metadata),
            "anchor_hash": _hash(anchors),
            "relation_hash": _hash(relation_data),
        }

    async def create_run(
        self,
        project_id: str,
        dry_run: bool = True,
        *,
        anchored_path: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        defer_detection: bool = False,
    ) -> dict:
        if not project_id or not str(project_id).strip():
            raise ValueError("project_id is required")
        if self.llm_configured is False:
            raise ReconcilerValidationError("reconciler LLM is not configured")
        project_id = str(project_id).strip()
        anchored_path = normalize_anchored_path(anchored_path)
        after_value = (
            created_after.astimezone(timezone.utc).isoformat()
            if created_after is not None
            else None
        )
        before_value = (
            created_before.astimezone(timezone.utc).isoformat()
            if created_before is not None
            else None
        )
        scope = {
            "anchored_path": anchored_path,
            "created_after": after_value,
            "created_before": before_value,
        }
        policy = await self._policy(project_id)
        if self.llm_base_url is not None and not await self._llm_allowed(
            project_id, self.llm_base_url
        ):
            raise ReconcilerValidationError(
                "external LLM is not allowed for this project"
            )
        policy_hash = _hash(policy.model_dump())
        run_id = "rr_" + uuid4().hex
        now = _now()
        budget = {
            "max_group_memories": MAX_GROUP_MEMORIES,
            "max_provenance_sources": MAX_PROVENANCE_SOURCES,
            "max_temporal_window_days": MAX_TEMPORAL_WINDOW_DAYS,
            "max_evidence_chars": MAX_EVIDENCE_CHARS,
            "max_estimated_input_tokens_per_group": MAX_ESTIMATED_INPUT_TOKENS_PER_GROUP,
            "max_estimated_input_tokens_per_run": MAX_ESTIMATED_INPUT_TOKENS_PER_RUN,
            "max_llm_calls": MAX_LLM_CALLS_PER_RUN,
            "max_activations": MAX_ACTIVATIONS_PER_RUN,
            "max_seconds": MAX_RUN_SECONDS,
        }
        async with self.db.transaction():
            queued = await self.db.fetchone(
                "SELECT COUNT(*) AS n FROM reconciler_runs WHERE status = 'queued'"
            )
            status = (
                "queued"
                if defer_detection and int(queued["n"]) < MAX_QUEUED_DETECTIONS
                else "retryable" if defer_detection else "detecting"
            )
            await self.db.execute(
                "INSERT INTO reconciler_runs(id, project_id, status, dry_run, detector_version, policy_hash, model, prompt_version, budget_json, stats_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    project_id,
                    status,
                    int(dry_run),
                    DETECTOR_VERSION,
                    policy_hash,
                    self.model,
                    self.prompt_version,
                    canonical_json(budget),
                    canonical_json(
                        {
                            "snapshot_count": 0,
                            "scope": scope,
                            "policy": policy.model_dump(),
                            "llm_configuration": {
                                "provider": self.provider or "unknown",
                                "model": self.model or "unknown",
                                "endpoint_scope": (
                                    "unknown"
                                    if self.llm_base_url is None
                                    else (
                                        "external"
                                        if is_external_llm_endpoint(self.llm_base_url)
                                        else "local"
                                    )
                                ),
                                "data_classification": "project_memory_evidence",
                            },
                        }
                    ),
                    now,
                    now,
                ),
            )
        if defer_detection:
            return await self.get_run(run_id)
        return await self._detect_run(run_id)

    async def _detect_run(self, run_id: str, lease_token: Optional[str] = None) -> dict:
        run = await self.db.fetchone(
            "SELECT * FROM reconciler_runs WHERE id = ?", (run_id,)
        )
        if not run:
            raise ValueError("reconciler run not found")
        if run["status"] == "cancelled":
            return await self.get_run(run_id)
        if run["detector_version"] != DETECTOR_VERSION:
            raise ReconcilerValidationError(
                "candidate detector changed before detection; start a new run"
            )
        project_id = str(run["project_id"])
        dry_run = bool(run["dry_run"])
        policy_hash = str(run["policy_hash"])
        if _hash((await self._policy(project_id)).model_dump()) != policy_hash:
            raise ReconcilerValidationError(
                "project policy changed before detection; start a new run"
            )
        scope = json.loads(run["stats_json"] or "{}").get("scope", {})
        anchored_path = scope.get("anchored_path")
        after_value = scope.get("created_after")
        before_value = scope.get("created_before")
        scoped_values = {
            key: value for key, value in scope.items() if value is not None
        }
        now = _now()
        query = (
            "SELECT * FROM memories WHERE project_id = ? "
            "AND COALESCE(status, 'canonical') = 'canonical' "
            "AND reconciler_protected = 0"
        )
        params: List[Any] = [project_id]
        if after_value:
            query += " AND datetime(created_at) >= datetime(?)"
            params.append(after_value)
        if before_value:
            query += " AND datetime(created_at) <= datetime(?)"
            params.append(before_value)
        anchor_condition, anchor_params = anchored_path_filter_clause(anchored_path)
        if anchor_condition:
            query += " AND " + anchor_condition
            params.extend(anchor_params)
        rows = await self.db.fetchall(query + " ORDER BY created_at, id", tuple(params))
        covered_ids = await self._active_source_ids(project_id)
        rows = [row for row in rows if str(row["id"]) not in covered_ids]
        pin_rows = await self.db.fetchall(
            "SELECT id, session_id, promoted_to_memory_id FROM pins WHERE project_id = ? AND promoted_to_memory_id IS NOT NULL ORDER BY created_at, id",
            (project_id,),
        )
        provenance_by_memory: dict[str, dict[str, list[str]]] = {}
        for pin in pin_rows:
            source = provenance_by_memory.setdefault(
                str(pin["promoted_to_memory_id"]),
                {"pin_ids": [], "session_ids": []},
            )
            source["pin_ids"].append(str(pin["id"]))
            if pin["session_id"]:
                session_id = str(pin["session_id"])
                if session_id not in source["session_ids"]:
                    source["session_ids"].append(session_id)
        snapshots = [
            await self._snapshot_memory(row, provenance_by_memory.get(str(row["id"])))
            for row in rows
        ]
        vectors: dict[str, np.ndarray] = {}
        stored_model = await self.db.get_embedding_metadata("embedding_model")
        if stored_model and stored_model == getattr(
            self.embedding_service, "model_name", None
        ):
            for row in rows:
                value = row["embedding"]
                if not isinstance(value, (bytes, bytearray, memoryview)):
                    continue
                value = bytes(value)
                if len(value) != self.db.embedding_dim * 4:
                    continue
                vector = np.frombuffer(value, dtype=np.float32)
                magnitude = float(np.linalg.norm(vector))
                if magnitude and np.isfinite(magnitude):
                    vectors[str(row["id"])] = vector / magnitude
        scaler = getattr(self.embedding_service, "scaled_threshold", None)
        embedding_threshold = scaler(0.7) if callable(scaler) else 0.7
        groups = self._detect_groups(snapshots, vectors, embedding_threshold)
        async with self.db.transaction():
            current = await self.db.fetchone(
                "SELECT status, stats_json FROM reconciler_runs WHERE id = ?", (run_id,)
            )
            if not current or current["status"] == "cancelled":
                return {"id": run_id, "status": "cancelled"}
            current_stats = json.loads(current["stats_json"] or "{}")
            if (
                lease_token
                and current_stats.get("detection_lease_token") != lease_token
            ):
                return {"id": run_id, "status": current["status"]}
            if not lease_token and current_stats.get("detection_lease_token"):
                return {"id": run_id, "status": current["status"]}
            current_stats["snapshot_count"] = len(snapshots)
            current_stats["candidate_group_count"] = len(groups)
            current_stats["deduplicated_candidate_count"] = 0
            retain_content = current_stats.get("policy", {}).get(
                "retain_evidence_content", True
            )
            await self.db.execute(
                "UPDATE reconciler_runs SET stats_json = ?, updated_at = ? WHERE id = ?",
                (canonical_json(current_stats), _now(), run_id),
            )
            for snapshot in snapshots:
                stored_snapshot = snapshot
                if not retain_content:
                    stored_snapshot = {
                        key: value
                        for key, value in snapshot.items()
                        if key
                        not in {"content", "title", "anchors", "metadata", "relations"}
                    }
                    stored_snapshot["content_retained"] = False
                    stored_snapshot["metadata"] = {
                        key: value
                        for key, value in snapshot["metadata"].items()
                        if key != "tags"
                    }
                    stored_snapshot["relations"] = [
                        {
                            key: value
                            for key, value in relation.items()
                            if key != "metadata"
                        }
                        for relation in snapshot["relations"]
                    ]
                await self.db.execute(
                    "INSERT INTO reconciler_inputs(id, run_id, project_id, memory_id, input_hash, content_hash, metadata_hash, relation_hash, anchor_hash, snapshot_json, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "ri_" + uuid4().hex,
                        run_id,
                        project_id,
                        snapshot["memory_id"],
                        snapshot["input_hash"],
                        snapshot["content_hash"],
                        snapshot["metadata_hash"],
                        snapshot["relation_hash"],
                        snapshot["anchor_hash"],
                        canonical_json(stored_snapshot),
                        now,
                    ),
                )

            for index, (members, signals) in enumerate(groups):
                ids = [item["memory_id"] for item in members]
                hash_payload = {
                    "project_id": project_id,
                    "memory_ids": ids,
                    "input_hashes": [item["input_hash"] for item in members],
                    "policy_hash": policy_hash,
                    "detector": run["detector_version"],
                    "prompt_version": run["prompt_version"],
                    "model": run["model"],
                    "llm_configuration": current_stats.get("llm_configuration", {}),
                    "dry_run": dry_run,
                }
                if scoped_values:
                    hash_payload["scope"] = scoped_values
                input_policy_hash = _hash(hash_payload)
                candidate_id = (
                    "rc_"
                    + hashlib.sha256(input_policy_hash.encode("utf-8")).hexdigest()[:32]
                )
                inserted = await self.db.execute(
                    "INSERT INTO reconciler_candidates(id, run_id, project_id, group_key, memory_ids_json, signal_json, input_policy_hash, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_judgment', ?, ?) ON CONFLICT(project_id, input_policy_hash) DO NOTHING",
                    (
                        candidate_id,
                        run_id,
                        project_id,
                        "cg_"
                        + hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[
                            :24
                        ],
                        canonical_json(ids),
                        canonical_json(signals),
                        input_policy_hash,
                        now,
                        now,
                    ),
                )
                if inserted.rowcount == 0:
                    current_stats["deduplicated_candidate_count"] += 1
            current_stats.pop("detection_lease_token", None)
            await self.db.execute(
                "UPDATE reconciler_runs SET status = 'judging', stats_json = ?, updated_at = ? WHERE id = ?",
                (
                    canonical_json({**current_stats, "detection_completed_at": _now()}),
                    _now(),
                    run_id,
                ),
            )
        candidate_count = await self.db.fetchone(
            "SELECT COUNT(*) AS count FROM reconciler_candidates WHERE run_id = ?",
            (run_id,),
        )
        if not candidate_count or not candidate_count["count"]:
            await self._finish_run(run_id, "completed")
        return await self.get_run(run_id)

    async def _active_source_ids(self, project_id: str) -> set[str]:
        covered: set[str] = set()
        for result in await self.effective_read._active_results(project_id):
            if result.get("action") in {"add_relation", "mark_stale"}:
                continue
            result_id = str(result["id"])
            if await self.effective_read.revalidate_result(result_id):
                covered.update(
                    str(source["memory_id"])
                    for source in await self.effective_read._source_rows(result_id)
                )
        return covered

    async def cancel_run(self, run_id: str) -> dict:
        run = await self.db.fetchone(
            "SELECT status FROM reconciler_runs WHERE id = ?", (run_id,)
        )
        if not run:
            raise ValueError("reconciler run not found")
        if run["status"] in {
            "completed",
            "needs_approval",
            "cancelled",
            "failed",
            "partial_success",
        }:
            return await self.get_run(run_id)
        now = _now()
        async with self.db.transaction():
            changed = await self.db.execute(
                "UPDATE reconciler_runs SET status = 'cancelled', updated_at = ?, completed_at = ? WHERE id = ? AND status NOT IN ('completed', 'needs_approval', 'cancelled', 'failed', 'partial_success')",
                (now, now, run_id),
            )
            if changed.rowcount:
                await self.db.execute(
                    "UPDATE reconciler_candidates SET status = 'cancelled', terminal_reason = 'run cancelled', lease_owner = NULL, lease_until = NULL, updated_at = ? WHERE run_id = ? AND status IN ('pending_judgment', 'processing', 'needs_approval')",
                    (now, run_id),
                )
                await self.db.execute(
                    "UPDATE reconciler_proposals SET status = 'cancelled', updated_at = ? WHERE run_id = ? AND status = 'needs_approval'",
                    (now, run_id),
                )
        return await self.get_run(run_id)

    def _detect_groups(
        self,
        snapshots: Sequence[dict],
        vectors: dict[str, np.ndarray],
        embedding_threshold: float,
    ) -> List[Tuple[List[dict], List[dict]]]:
        groups: List[List[dict]] = []
        signals_by_group: List[List[dict]] = []
        creation_times: dict[str, datetime] = {}
        for item in snapshots:
            try:
                timestamp = datetime.fromisoformat(
                    str(item["metadata"].get("created_at", "")).replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ReconcilerValidationError(
                    "invalid memory creation time; temporal scope cannot be verified"
                ) from exc
            creation_times[item["memory_id"]] = timestamp.replace(
                tzinfo=timestamp.tzinfo or timezone.utc
            ).astimezone(timezone.utc)
        threshold = 0.35
        for snapshot in snapshots:
            placed = False
            for index, group in enumerate(groups):
                group_times = [creation_times[item["memory_id"]] for item in group]
                group_times.append(creation_times[snapshot["memory_id"]])
                if max(group_times) - min(group_times) > timedelta(
                    days=MAX_TEMPORAL_WINDOW_DAYS
                ):
                    continue
                first = group[0]
                same_day = (
                    str(snapshot["metadata"].get("created_at", ""))[:10]
                    == str(first["metadata"].get("created_at", ""))[:10]
                )
                semantic = _similarity(snapshot["content"], first["content"])
                left = vectors.get(snapshot["memory_id"])
                right = vectors.get(first["memory_id"])
                embedding_similarity = (
                    float(np.dot(left, right))
                    if left is not None and right is not None
                    else 0.0
                )
                same_source = snapshot["metadata"].get("source") == first[
                    "metadata"
                ].get("source")
                same_anchor = bool(
                    snapshot.get("anchors")
                    and snapshot.get("anchors") == first.get("anchors")
                )
                group_ids = {item["memory_id"] for item in group}
                connected_relation = next(
                    (
                        relation
                        for relation in snapshot.get("relations", [])
                        if relation.get("relation_type")
                        in {
                            "related",
                            "references",
                            "depends_on",
                            "supersedes",
                            "similar",
                        }
                        and (
                            (
                                relation.get("source_id") == snapshot["memory_id"]
                                and relation.get("target_id") in group_ids
                            )
                            or (
                                relation.get("target_id") == snapshot["memory_id"]
                                and relation.get("source_id") in group_ids
                            )
                        )
                    ),
                    None,
                )
                if (
                    (same_day and semantic >= threshold)
                    or semantic >= 0.65
                    or embedding_similarity >= embedding_threshold
                    or same_anchor
                    or connected_relation
                ):
                    if (
                        len(group) < MAX_GROUP_MEMORIES
                        and len(
                            {
                                item["metadata"].get("source")
                                for item in group + [snapshot]
                            }
                        )
                        <= MAX_PROVENANCE_SOURCES
                    ):
                        group.append(snapshot)
                        if semantic:
                            signals_by_group[index].append(
                                {"kind": "lexical_overlap", "score": round(semantic, 4)}
                            )
                        if embedding_similarity >= embedding_threshold:
                            signals_by_group[index].append(
                                {
                                    "kind": "embedding_similarity",
                                    "score": round(embedding_similarity, 4),
                                }
                            )
                        if same_day:
                            signals_by_group[index].append(
                                {"kind": "same_day", "score": 1.0}
                            )
                        if same_source:
                            signals_by_group[index].append(
                                {"kind": "same_provenance", "score": 1.0}
                            )
                        if connected_relation:
                            signals_by_group[index].append(
                                {
                                    "kind": "graph_relation",
                                    "relation_type": connected_relation[
                                        "relation_type"
                                    ],
                                    "score": float(
                                        connected_relation.get("strength") or 0
                                    ),
                                }
                            )
                        placed = True
                        break
            if not placed:
                groups.append([snapshot])
                signals_by_group.append([])
        candidates = []
        automatic_sources = {"hook", "session", "agent", "auto", "automation"}
        for index, group in enumerate(groups):
            if len(group) > 1 or any(
                item["metadata"].get("source") in automatic_sources for item in group
            ):
                candidates.append((group, signals_by_group[index]))
        return candidates

    async def _claim_detection_run(self, worker_id: str) -> Optional[dict]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=DETECTION_LEASE_SECONDS)
        ).isoformat()
        async with self.db.transaction():
            row = await self.db.fetchone(
                "SELECT id, stats_json FROM reconciler_runs "
                "WHERE status IN ('queued', 'retryable') "
                "OR (status = 'detecting' AND updated_at < ?) "
                "ORDER BY created_at, id LIMIT 1",
                (cutoff,),
            )
            if not row:
                return None
            token = uuid4().hex
            stats = json.loads(row["stats_json"] or "{}")
            stats["detection_lease_token"] = token
            stats["detection_worker"] = worker_id
            await self.db.execute(
                "UPDATE reconciler_runs SET status = 'detecting', stats_json = ?, updated_at = ? WHERE id = ?",
                (canonical_json(stats), _now(), row["id"]),
            )
            return {"id": row["id"], "lease_token": token}

    async def _claim_candidate(self, worker_id: str) -> Optional[dict]:
        cutoff = _epoch()
        async with self.db.transaction():
            row = await self.db.fetchone(
                "SELECT * FROM reconciler_candidates WHERE status = 'pending_judgment' OR (status = 'processing' AND COALESCE(lease_until, 0) < ?) ORDER BY created_at, id LIMIT 1",
                (cutoff,),
            )
            if not row:
                return None
            lease_until = _epoch() + self.lease_seconds
            cur = await self.db.execute(
                "UPDATE reconciler_candidates SET status = 'processing', lease_owner = ?, lease_until = ?, updated_at = ? WHERE id = ? AND (status = 'pending_judgment' OR (status = 'processing' AND COALESCE(lease_until, 0) < ?))",
                (worker_id, lease_until, _now(), row["id"], cutoff),
            )
            if cur.rowcount != 1:
                return None
            return {
                **dict(row),
                "status": "processing",
                "lease_owner": worker_id,
                "lease_until": lease_until,
            }

    async def _has_candidate_lease(self, candidate: dict) -> bool:
        row = await self.db.fetchone(
            "SELECT status, lease_owner, lease_until FROM reconciler_candidates WHERE id = ?",
            (candidate["id"],),
        )
        return bool(
            row
            and row["status"] == "processing"
            and row["lease_owner"] == candidate["lease_owner"]
            and row["lease_until"] == candidate["lease_until"]
        )

    async def _evidence(self, candidate: dict) -> List[dict]:
        rows = await self.db.fetchall(
            "SELECT snapshot_json FROM reconciler_inputs WHERE run_id = ? AND memory_id IN (SELECT value FROM json_each(?)) ORDER BY memory_id",
            (candidate["run_id"], candidate["memory_ids_json"]),
        )
        evidence = [json.loads(row["snapshot_json"]) for row in rows]
        for item in evidence:
            excluded = item.get(
                "content_excluded_reason"
            ) or reconciler_evidence_exclusion(item.get("content", ""))
            if excluded:
                raise ReconcilerValidationError(
                    f"excluded evidence: {excluded}; use distilled project facts"
                )
        for item in evidence:
            if item.get("content_retained") is False:
                source = await self.db.fetchone(
                    "SELECT * FROM memories WHERE id = ?", (item["memory_id"],)
                )
                if (
                    not source
                    or await self.effective_read.current_input_hash(item["memory_id"])
                    != item["input_hash"]
                ):
                    raise ReconcilerValidationError(
                        "canonical input hash changed before evidence reconstruction"
                    )
                reconstructed = await self._snapshot_memory(
                    source, item.get("provenance")
                )
                if reconstructed.get("content_excluded_reason"):
                    raise ReconcilerValidationError(
                        f"excluded evidence: {reconstructed['content_excluded_reason']}; use distilled project facts"
                    )
                if reconstructed["input_hash"] != item["input_hash"]:
                    raise ReconcilerValidationError(
                        "canonical input hash changed during evidence reconstruction"
                    )
                for field in ("content", "title", "anchors"):
                    item[field] = reconstructed[field]
        if any(item.get("content_truncated") for item in evidence):
            raise ReconcilerValidationError(
                "source content exceeds evidence limit; split or review"
            )
        signals = json.loads(candidate["signal_json"] or "[]")
        for item in evidence:
            item["detector_signals"] = signals
        chars = len(canonical_json(evidence))
        estimated_tokens = max(1, chars // 4)
        if chars > MAX_EVIDENCE_CHARS:
            raise ReconcilerValidationError("evidence character budget exceeded")
        if estimated_tokens > MAX_ESTIMATED_INPUT_TOKENS_PER_GROUP:
            raise ReconcilerValidationError("evidence token budget exceeded")
        return evidence

    async def _reserve_judge_call(
        self, run_id: str, evidence: List[dict], judge_context: dict
    ) -> Optional[str]:
        estimated_tokens = max(1, len(canonical_json(evidence)) // 4)
        async with self.db.transaction():
            run = await self.db.fetchone(
                "SELECT status, project_id, policy_hash, created_at, budget_json, stats_json FROM reconciler_runs WHERE id = ?",
                (run_id,),
            )
            if not run:
                return "reconciler run not found"
            if run["status"] == "cancelled":
                return "run cancelled"
            if (
                _hash((await self._policy(run["project_id"])).model_dump())
                != run["policy_hash"]
            ):
                return "run policy changed before judgment; start a new run"
            budget = json.loads(run["budget_json"] or "{}")
            stats = json.loads(run["stats_json"] or "{}")
            configured_provider = stats.get("llm_configuration", {}).get("provider")
            if configured_provider not in {None, "unknown", judge_context["provider"]}:
                return "run provider changed before judgment; start a new run"
            created_at = datetime.fromisoformat(
                str(stats.get("detection_completed_at") or run["created_at"])
            )
            if _epoch() - created_at.timestamp() >= int(budget["max_seconds"]):
                return "run time budget exceeded"
            calls = int(stats.get("llm_calls", 0))
            if calls >= int(budget["max_llm_calls"]):
                return "run LLM call budget exceeded"
            total_tokens = int(stats.get("estimated_input_tokens", 0))
            if total_tokens + estimated_tokens > int(
                budget["max_estimated_input_tokens_per_run"]
            ):
                return "run input token budget exceeded"
            stats["llm_calls"] = calls + 1
            stats["estimated_input_tokens"] = total_tokens + estimated_tokens
            contexts = stats.setdefault("judge_contexts", [])
            if judge_context not in contexts:
                contexts.append(judge_context)
            await self.db.execute(
                "UPDATE reconciler_runs SET stats_json = ?, updated_at = ? WHERE id = ?",
                (canonical_json(stats), _now(), run_id),
            )
        return None

    async def _record_provider_usage(self, run_id: str, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        keys = (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
        if any(
            not isinstance(usage.get(key), int)
            or isinstance(usage[key], bool)
            or usage[key] < 0
            for key in keys
        ):
            return
        async with self.db.transaction():
            row = await self.db.fetchone(
                "SELECT stats_json FROM reconciler_runs WHERE id = ?", (run_id,)
            )
            if not row:
                return
            stats = json.loads(row["stats_json"] or "{}")
            stats["reported_usage_calls"] = (
                int(stats.get("reported_usage_calls", 0)) + 1
            )
            for key in keys:
                field = "reported_" + key
                stats[field] = int(stats.get(field, 0)) + usage[key]
            await self.db.execute(
                "UPDATE reconciler_runs SET stats_json = ?, updated_at = ? WHERE id = ?",
                (canonical_json(stats), _now(), run_id),
            )

    async def _call_judge(
        self, enricher: Any, evidence: List[dict], repair_error: Optional[str] = None
    ) -> dict:
        method = (
            getattr(enricher, "_repair_reconcile_group", None) if repair_error else None
        )
        if method is not None:
            result = await method(evidence, repair_error)
        else:
            method = getattr(enricher, "reconcile_group", None)
            if method is not None:
                result = await method(evidence)
            else:
                method = getattr(enricher, "judge", None)
                if method is not None:
                    result = await method(evidence)
                else:
                    raise ReconcilerValidationError(
                        "provider has no group judgment method"
                    )
        if not isinstance(result, dict):
            raise ReconcilerValidationError("provider result must be an object")
        return result

    def _normalize_payload(self, payload: dict, evidence: List[dict]) -> dict:
        allowed_verdicts = {
            "supersede_old": "supersede",
            "supersede_new": "supersede",
            "merge": "merge",
            "keep_both": "keep",
            "conflict": "needs_review",
        }
        action = (
            str(payload.get("action") or payload.get("verdict") or "needs_review")
            .strip()
            .lower()
        )
        explicit_conflict = action == "conflict"
        action = allowed_verdicts.get(action, action)
        if action not in RECONCILER_ACTIONS:
            raise ReconcilerValidationError(f"unsupported action: {action}")
        review_reason = payload.get("review_reason")
        if review_reason is None and explicit_conflict:
            review_reason = "contradiction"
        if review_reason is not None:
            if not isinstance(review_reason, str) or review_reason not in {
                "contradiction",
                "insufficient_evidence",
                "scope_mismatch",
                "uncertain_provenance",
                "other",
            }:
                raise ReconcilerValidationError("unsupported review_reason")
            if action != "needs_review":
                raise ReconcilerValidationError(
                    "review_reason requires needs_review action"
                )
        members = {item["memory_id"]: item for item in evidence}
        representative = payload.get("representative_memory_id") or payload.get(
            "representative_id"
        )
        if action in {"merge", "supersede"} and not representative:
            raise ReconcilerValidationError("representative is required")
        if representative is None and evidence:
            representative = evidence[-1]["memory_id"]
        if representative not in members:
            raise ReconcilerValidationError("representative is outside candidate group")
        body = (
            payload.get("body")
            or payload.get("synthesized_body")
            or payload.get("merged_text")
        )
        if action in {"merge", "supersede"} and not body:
            raise ReconcilerValidationError("body is required")
        if (
            action not in {"merge", "supersede", "keep", "no_op", "needs_review"}
            and not body
        ):
            body = members[representative]["content"]
        body = redact_secrets(str(body or ""))[:MAX_EVIDENCE_CHARS]
        claims = payload.get("claims") or []
        if action in {"merge", "supersede"} and not claims:
            raise ReconcilerValidationError("claims are required")
        normalized_claims = []
        omitted_uncited_claims = False
        for raw_claim in claims:
            if not isinstance(raw_claim, dict):
                raise ReconcilerValidationError("claim must be an object")
            refs = (
                raw_claim.get("source_refs")
                or raw_claim.get("explicit_source_refs")
                or []
            )
            if not refs:
                if action == "needs_review":
                    # The observed provider failure omitted source_refs on held claims.
                    omitted_uncited_claims = True
                    continue
                raise ReconcilerValidationError("claim source_refs are required")
            raw_conditions = raw_claim.get("conditions") or []
            if isinstance(raw_conditions, str):
                raw_conditions = [raw_conditions]
            claim = ReconcilerClaim(
                claim_id=str(raw_claim.get("claim_id") or uuid4().hex),
                text=str(raw_claim.get("text") or ""),
                conditions=[str(item) for item in raw_conditions],
                source_refs=refs,
            )
            if any(
                ref.memory_id not in members
                or members[ref.memory_id]["input_hash"] != ref.input_hash
                for ref in claim.source_refs
            ):
                raise ReconcilerValidationError(
                    "claim source is outside candidate snapshot or has a stale hash"
                )
            normalized_claims.append(claim.model_dump())
        relations = payload.get("relations") or []
        if action == "add_relation" and not relations:
            raise ReconcilerValidationError("relations are required")
        dependencies = {memory_id: set() for memory_id in members}
        normalized_relations = []
        for relation in relations:
            if not isinstance(relation, dict) or relation.get("relation_type") not in {
                "related",
                "depends_on",
                "references",
                "similar",
            }:
                raise ReconcilerValidationError("invalid derived relation")
            if (
                relation.get("source_id") not in members
                or relation.get("target_id") not in members
            ):
                raise ReconcilerValidationError(
                    "derived relation source is outside candidate group"
                )
            if relation["relation_type"] == "depends_on":
                dependencies[relation["source_id"]].add(relation["target_id"])
            normalized_relations.append(
                {
                    "source_id": relation["source_id"],
                    "target_id": relation["target_id"],
                    "relation_type": relation["relation_type"],
                }
            )
        remaining = set(dependencies)
        while remaining:
            ready = {
                memory_id
                for memory_id in remaining
                if not (dependencies[memory_id] & remaining)
            }
            if not ready:
                raise ReconcilerValidationError("derived dependency cycle")
            remaining -= ready
        rationale = str(payload.get("rationale") or "")
        if omitted_uncited_claims:
            rationale = f"{rationale} Uncited claims were omitted.".strip()
        explanation = {}
        for field in ("preserved_conditions", "removed_repetition", "uncertainties"):
            values = payload.get(field, [])
            if not isinstance(values, list) or any(
                not isinstance(value, str) for value in values
            ):
                raise ReconcilerValidationError(f"{field} must be an array of strings")
            if len(canonical_json(values)) > MAX_EVIDENCE_CHARS:
                raise ReconcilerValidationError(f"{field} exceeds output budget")
            explanation[field] = values
        return _redact_evidence(
            {
                **explanation,
                "action": action,
                "review_reason": review_reason,
                "representative_memory_id": representative,
                "body": body,
                "claims": normalized_claims,
                "relations": normalized_relations,
                "rationale": rationale[:1000],
                "risk": str(payload.get("risk") or "")[:100],
                "confidence": payload.get("confidence"),
            }
        )

    async def process_next(
        self, worker_id: str, enricher: Any, conflict_detector: Any = None
    ) -> dict:
        detection = await self._claim_detection_run(worker_id)
        if detection:
            try:
                run = await self._detect_run(detection["id"], detection["lease_token"])
                return {
                    "run_id": detection["id"],
                    "processed": run["status"] in {"judging", "completed"},
                    "status": run["status"],
                }
            except Exception as exc:
                async with self.db.transaction():
                    state = await self.db.fetchone(
                        "SELECT status, stats_json FROM reconciler_runs WHERE id = ?",
                        (detection["id"],),
                    )
                    stats = json.loads(state["stats_json"] or "{}") if state else {}
                    if (
                        state
                        and state["status"] == "detecting"
                        and stats.get("detection_lease_token")
                        == detection["lease_token"]
                    ):
                        await self.db.execute(
                            "UPDATE reconciler_runs SET status = 'failed', error = ?, updated_at = ?, completed_at = ? WHERE id = ?",
                            (str(exc)[:1000], _now(), _now(), detection["id"]),
                        )
                logger.exception("Memory Reconciler detection failed")
                return {
                    "run_id": detection["id"],
                    "processed": False,
                    "error": str(exc),
                }
        candidate = await self._claim_candidate(worker_id)
        if candidate is None:
            if self._legacy_service is None:
                from .reconcile import ReconcileService

                self._legacy_service = ReconcileService(
                    self.db, can_send_llm=self._llm_allowed, **self._legacy_options
                )
            return await self._legacy_service.process_next(
                worker_id=worker_id,
                enricher=enricher,
                conflict_detector=conflict_detector,
            )
        proposal_committed = False
        try:
            run_model = await self.db.fetchone(
                "SELECT model, prompt_version, detector_version FROM reconciler_runs WHERE id = ?",
                (candidate["run_id"],),
            )
            recorded_model = str(run_model["model"] or "") if run_model else ""
            version_change = None
            if run_model and run_model["detector_version"] != DETECTOR_VERSION:
                version_change = "detector"
            elif run_model and run_model["prompt_version"] != self.prompt_version:
                version_change = "prompt"
            if version_change:
                reason = (
                    f"run {version_change} changed before judgment; start a new run"
                )
                await self._finish_candidate(
                    candidate["id"], "needs_review", reason, lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "needs_review",
                    "error": reason,
                }
            judge_model = str(getattr(enricher, "model", "") or "")
            if recorded_model and judge_model and recorded_model != judge_model:
                reason = "run model changed before judgment; start a new run"
                await self._finish_candidate(
                    candidate["id"], "needs_review", reason, lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "needs_review",
                    "error": reason,
                }
            try:
                evidence = await self._evidence(candidate)
            except ReconcilerValidationError as exc:
                reason = str(exc)
                await self._finish_candidate(
                    candidate["id"], "needs_review", reason, lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "needs_review",
                    "error": reason,
                }
            protected_source = None
            for item in evidence:
                current = await self.db.fetchone(
                    "SELECT reconciler_protected FROM memories WHERE id = ?",
                    (item["memory_id"],),
                )
                if current and current["reconciler_protected"]:
                    protected_source = item["memory_id"]
                    break
            if protected_source:
                reason = "source is protected from Reconciler LLM judgment"
                await self._finish_candidate(
                    candidate["id"], "needs_review", reason, lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "needs_review",
                    "error": reason,
                }
            changed_input = False
            for item in evidence:
                current_hash = await self.effective_read.current_input_hash(
                    item["memory_id"]
                )
                if current_hash != item["input_hash"]:
                    changed_input = True
                    break
            if changed_input:
                reason = "canonical input hash changed before judgment; start a new run"
                await self._finish_candidate(
                    candidate["id"], "needs_review", reason, lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "needs_review",
                    "error": reason,
                }
            if any(
                str(item.get("metadata", {}).get("stale_status") or "").lower()
                == "stale"
                for item in evidence
            ):
                reason = "source anchor is stale; refresh the source before judgment"
                await self._finish_candidate(
                    candidate["id"], "needs_review", reason, lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "needs_review",
                    "error": reason,
                }
            covered_ids = await self._active_source_ids(candidate["project_id"])
            member_ids = {item["memory_id"] for item in evidence}
            overlap = member_ids & covered_ids
            if overlap:
                status = "no_op" if overlap == member_ids else "needs_review"
                reason = (
                    "already covered by an active curated result"
                    if status == "no_op"
                    else "candidate overlaps an active curated result; start a new run"
                )
                await self._finish_candidate(
                    candidate["id"], status, reason, lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": status,
                    "error": reason,
                }
            payload = None
            error = None
            repair_error = None
            for _ in range(JUDGE_REPAIR_RETRIES + 1):
                if not await self._has_candidate_lease(candidate):
                    return {
                        "candidate_id": candidate["id"],
                        "processed": False,
                        "status": "lease_lost",
                    }
                if not await self._llm_allowed(
                    candidate["project_id"], getattr(enricher, "base_url", "")
                ):
                    reason = "external LLM is not allowed for this project"
                    await self._finish_candidate(
                        candidate["id"], "needs_review", reason, lease=candidate
                    )
                    return {
                        "candidate_id": candidate["id"],
                        "processed": True,
                        "status": "needs_review",
                        "error": reason,
                    }
                budget_error = await self._reserve_judge_call(
                    candidate["run_id"],
                    evidence,
                    {
                        "provider": str(
                            getattr(enricher, "provider_name", "") or "unknown"
                        ),
                        "model": str(getattr(enricher, "model", "") or "unknown"),
                        "endpoint_scope": (
                            "external"
                            if is_external_llm_endpoint(
                                getattr(enricher, "base_url", "")
                            )
                            else "local"
                        ),
                        "data_classification": "project_memory_evidence",
                        "redaction": "configured_secret_redaction",
                        "evidence_fields": sorted(
                            {key for item in evidence for key in item}
                        ),
                        "metadata_fields": sorted(
                            {
                                key
                                for item in evidence
                                for key in item.get("metadata", {})
                            }
                        ),
                        "relation_fields": sorted(
                            {
                                key
                                for item in evidence
                                for relation in item.get("relations", [])
                                for key in relation
                            }
                        ),
                    },
                )
                if budget_error:
                    if budget_error == "run cancelled":
                        return {
                            "candidate_id": candidate["id"],
                            "processed": False,
                            "status": "cancelled",
                        }
                    await self._finish_candidate(
                        candidate["id"], "needs_review", budget_error, lease=candidate
                    )
                    return {
                        "candidate_id": candidate["id"],
                        "processed": True,
                        "status": "needs_review",
                        "error": budget_error,
                    }
                try:
                    if hasattr(enricher, "last_usage"):
                        enricher.last_usage = None
                    try:
                        payload = await self._call_judge(
                            enricher, evidence, repair_error=repair_error
                        )
                    finally:
                        await self._record_provider_usage(
                            candidate["run_id"],
                            getattr(enricher, "last_usage", None),
                        )
                    normalized = self._normalize_payload(payload, evidence)
                    break
                except Exception as exc:
                    async with self.db.transaction():
                        usage_row = await self.db.fetchone(
                            "SELECT stats_json FROM reconciler_runs WHERE id = ?",
                            (candidate["run_id"],),
                        )
                        if usage_row:
                            stats = json.loads(usage_row["stats_json"] or "{}")
                            stats["judge_failed_calls"] = (
                                int(stats.get("judge_failed_calls", 0)) + 1
                            )
                            await self.db.execute(
                                "UPDATE reconciler_runs SET stats_json = ?, updated_at = ? WHERE id = ?",
                                (canonical_json(stats), _now(), candidate["run_id"]),
                            )
                    error = str(exc)
                    repair_error = (
                        error if isinstance(exc, ReconcilerValidationError) else None
                    )
                    normalized = None
            run_state = await self.db.fetchone(
                "SELECT status FROM reconciler_runs WHERE id = ?",
                (candidate["run_id"],),
            )
            if run_state and run_state["status"] == "cancelled":
                return {
                    "candidate_id": candidate["id"],
                    "processed": False,
                    "status": "cancelled",
                }
            if not await self._has_candidate_lease(candidate):
                return {
                    "candidate_id": candidate["id"],
                    "processed": False,
                    "status": "lease_lost",
                }
            if normalized is None:
                await self._finish_candidate(
                    candidate["id"],
                    "failed",
                    error or "invalid provider payload",
                    lease=candidate,
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": False,
                    "status": "failed",
                    "error": error,
                }
            if normalized["action"] in {"keep", "no_op"}:
                await self._finish_candidate(
                    candidate["id"], "no_op", normalized["action"], lease=candidate
                )
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "no_op",
                }
            proposal_id = (
                "rp_"
                + hashlib.sha256(
                    (
                        candidate["input_policy_hash"]
                        + normalized["action"]
                        + normalized["body"]
                    ).encode("utf-8")
                ).hexdigest()[:32]
            )
            policy = await self._policy(candidate["project_id"])
            run_row = await self.db.fetchone(
                "SELECT dry_run FROM reconciler_runs WHERE id = ?",
                (candidate["run_id"],),
            )
            if not run_row:
                raise ReconcilerValidationError("reconciler run not found")
            dry_run = bool(run_row["dry_run"])
            is_hold = normalized["action"] == "needs_review"
            proposal_status = (
                "needs_review"
                if is_hold
                else "preview" if dry_run else "needs_approval"
            )
            now = _now()
            async with self.db.transaction():
                run_state = await self.db.fetchone(
                    "SELECT status FROM reconciler_runs WHERE id = ?",
                    (candidate["run_id"],),
                )
                if run_state and run_state["status"] == "cancelled":
                    return {
                        "candidate_id": candidate["id"],
                        "processed": False,
                        "status": "cancelled",
                    }
                if not await self._has_candidate_lease(candidate):
                    return {
                        "candidate_id": candidate["id"],
                        "processed": False,
                        "status": "lease_lost",
                    }
                await self.db.execute(
                    "INSERT INTO reconciler_proposals(id, candidate_id, run_id, project_id, action, status, representative_memory_id, body, claims_json, proposal_json, input_policy_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(candidate_id, input_policy_hash) DO NOTHING",
                    (
                        proposal_id,
                        candidate["id"],
                        candidate["run_id"],
                        candidate["project_id"],
                        normalized["action"],
                        proposal_status,
                        normalized["representative_memory_id"],
                        normalized["body"],
                        canonical_json(normalized["claims"]),
                        canonical_json(normalized),
                        candidate["input_policy_hash"],
                        now,
                        now,
                    ),
                )
                await self.db.execute(
                    "UPDATE reconciler_candidates SET status = ?, terminal_reason = ?, lease_owner = NULL, lease_until = NULL, updated_at = ? WHERE id = ?",
                    (
                        proposal_status,
                        (
                            "dry-run preview"
                            if dry_run
                            else "needs review hold" if is_hold else None
                        ),
                        now,
                        candidate["id"],
                    ),
                )
            proposal_committed = True
            proposal = await self.db.fetchone(
                "SELECT * FROM reconciler_proposals WHERE id = ?", (proposal_id,)
            )
            if not dry_run:
                if self._auto_allowed(normalized, evidence, policy):
                    activation = await self._activate_proposal(
                        proposal_id, int(proposal["expected_revision"]), actor="auto"
                    )
                    return {
                        "candidate_id": candidate["id"],
                        "processed": True,
                        "status": "active",
                        "result_id": activation.get("result_id"),
                    }
            await self._finish_run_if_ready(candidate["run_id"])
            return {
                "candidate_id": candidate["id"],
                "processed": True,
                "status": proposal_status,
                "proposal_id": proposal_id,
            }
        except ReconcilerConflictError as exc:
            if not proposal_committed and not await self._has_candidate_lease(
                candidate
            ):
                return {
                    "candidate_id": candidate["id"],
                    "processed": False,
                    "status": "lease_lost",
                }
            reason = str(exc)
            await self.db.execute(
                "UPDATE reconciler_proposals SET status = 'conflict', error = ?, updated_at = ? WHERE candidate_id = ? AND status = 'needs_approval'",
                (reason[:1000], _now(), candidate["id"]),
            )
            await self._finish_candidate(candidate["id"], "needs_review", reason)
            return {
                "candidate_id": candidate["id"],
                "processed": True,
                "status": "needs_review",
                "error": reason,
            }
        except Exception as exc:
            if not proposal_committed and not await self._has_candidate_lease(
                candidate
            ):
                return {
                    "candidate_id": candidate["id"],
                    "processed": False,
                    "status": "lease_lost",
                }
            if (
                isinstance(exc, ReconcilerValidationError)
                and exc.details.get("budget") == "activations"
            ):
                reason = str(exc)
                await self.db.execute(
                    "UPDATE reconciler_proposals SET status = 'needs_review', error = ?, updated_at = ? WHERE candidate_id = ? AND status = 'needs_approval'",
                    (reason[:1000], _now(), candidate["id"]),
                )
                await self._finish_candidate(candidate["id"], "needs_review", reason)
                return {
                    "candidate_id": candidate["id"],
                    "processed": True,
                    "status": "needs_review",
                    "error": reason,
                }
            await self._finish_candidate(
                candidate["id"],
                "failed",
                str(exc),
                lease=None if proposal_committed else candidate,
            )
            logger.exception("Memory Reconciler candidate failed")
            return {
                "candidate_id": candidate["id"],
                "processed": False,
                "error": str(exc),
            }

    @staticmethod
    def _auto_allowed(
        payload: dict, evidence: Sequence[dict], policy: ReconcilerPolicy
    ) -> bool:
        if any(
            str(item.get("metadata", {}).get("status") or "canonical") != "canonical"
            for item in evidence
        ):
            return False
        sources = {
            str(item.get("metadata", {}).get("source") or "").lower()
            for item in evidence
        }
        protected = any(
            str(item.get("metadata", {}).get("category") or "").lower()
            in {"decision", "incident"}
            for item in evidence
        )
        action = payload["action"]
        if action in {"merge", "supersede"}:
            return True
        sourced_auto = bool(sources) and all(
            source in {"hook", "session", "agent", "auto", "automation"}
            for source in sources
        )
        return (
            not protected
            and sourced_auto
            and (
                (
                    action in {"noise_suppression", "archive", "quarantine"}
                    and policy.auto_noise_suppression
                )
                or (action == "add_relation" and policy.auto_derived_relations)
            )
        )

    async def _finish_candidate(
        self,
        candidate_id: str,
        status: str,
        reason: str,
        *,
        lease: Optional[dict] = None,
    ) -> None:
        query = "UPDATE reconciler_candidates SET status = ?, terminal_reason = ?, lease_owner = NULL, lease_until = NULL, updated_at = ? WHERE id = ? AND status != 'cancelled' AND NOT EXISTS (SELECT 1 FROM reconciler_runs r WHERE r.id = reconciler_candidates.run_id AND r.status = 'cancelled')"
        params = (status, reason[:1000], _now(), candidate_id)
        if lease is not None:
            query += (
                " AND status = 'processing' AND lease_owner = ? AND lease_until = ?"
            )
            params += (lease["lease_owner"], lease["lease_until"])
        changed = await self.db.execute(query, params)
        if changed.rowcount != 1:
            return
        row = await self.db.fetchone(
            "SELECT run_id FROM reconciler_candidates WHERE id = ?", (candidate_id,)
        )
        if row:
            await self._finish_run_if_ready(row["run_id"])

    async def _finish_run(self, run_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE reconciler_runs SET status = ?, updated_at = ?, completed_at = ? WHERE id = ? AND status != 'cancelled'",
            (status, _now(), _now(), run_id),
        )

    async def _finish_run_if_ready(self, run_id: str) -> None:
        run = await self.db.fetchone(
            "SELECT status FROM reconciler_runs WHERE id = ?", (run_id,)
        )
        if run and run["status"] == "cancelled":
            return
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS remaining FROM reconciler_candidates WHERE run_id = ? AND status IN ('pending_judgment', 'processing')",
            (run_id,),
        )
        if row and int(row["remaining"]) == 0:
            pending = await self.db.fetchone(
                "SELECT COUNT(*) AS n FROM reconciler_proposals WHERE run_id = ? AND status IN ('needs_approval', 'approved')",
                (run_id,),
            )
            unresolved = await self.db.fetchone(
                "SELECT COUNT(*) AS n FROM reconciler_candidates c WHERE c.run_id = ? "
                "AND c.status = 'failed'",
                (run_id,),
            )
            unapplied_holds = await self.db.fetchone(
                "SELECT COUNT(*) AS n FROM reconciler_candidates c WHERE c.run_id = ? "
                "AND c.status = 'needs_review' AND (NOT EXISTS "
                "(SELECT 1 FROM reconciler_proposals p WHERE p.candidate_id = c.id) "
                "OR c.terminal_reason LIKE '%activation budget%')",
                (run_id,),
            )
            proposals = await self.db.fetchone(
                "SELECT COUNT(*) AS n FROM reconciler_proposals WHERE run_id = ?",
                (run_id,),
            )
            if pending and pending["n"]:
                status = "needs_approval"
            elif unresolved and unresolved["n"]:
                status = "partial_success" if proposals and proposals["n"] else "failed"
            elif (
                unapplied_holds
                and unapplied_holds["n"]
                and proposals
                and proposals["n"]
            ):
                status = "partial_success"
            else:
                status = "completed"
            await self._finish_run(run_id, status)

    async def get_run(self, run_id: str) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM reconciler_runs WHERE id = ?", (run_id,)
        )
        if not row:
            raise ValueError("reconciler run not found")
        result = dict(row)
        result["budget"] = json.loads(result.pop("budget_json") or "{}")
        result["stats"] = json.loads(result.pop("stats_json") or "{}")
        counts = await self.db.fetchall(
            "SELECT status, COUNT(*) AS count FROM reconciler_candidates WHERE run_id = ? GROUP BY status",
            (run_id,),
        )
        result["candidate_counts"] = {
            str(item["status"]): int(item["count"]) for item in counts
        }
        active = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM curated_results cr "
            "JOIN reconciler_proposals p ON p.id = cr.proposal_id "
            "WHERE p.run_id = ? AND cr.status = 'active'",
            (run_id,),
        )
        result["active_result_count"] = int(active["n"]) if active else 0
        issues = await self.db.fetchall(
            "SELECT c.id, c.status, c.terminal_reason FROM reconciler_candidates c "
            "WHERE c.run_id = ? AND (c.status = 'failed' OR "
            "(c.status = 'needs_review' AND NOT EXISTS "
            "(SELECT 1 FROM reconciler_proposals p WHERE p.candidate_id = c.id))) "
            "ORDER BY c.updated_at DESC, c.id LIMIT 5",
            (run_id,),
        )
        result["candidate_issues"] = [
            {
                "candidate_id": item["id"],
                "status": item["status"],
                "reason": item["terminal_reason"],
            }
            for item in issues
        ]
        return result

    async def list_runs(self, project_id: str, limit: int = 10) -> dict:
        rows = await self.db.fetchall(
            "SELECT id FROM reconciler_runs WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, max(1, min(limit, 50))),
        )
        runs = [await self.get_run(row["id"]) for row in rows]
        return {"project_id": project_id, "runs": runs, "count": len(runs)}

    async def list_candidates(
        self, run_id: str, project_id: str, limit: int = 50, offset: int = 0
    ) -> dict:
        run = await self.get_run(run_id)
        if run["project_id"] != project_id:
            raise ValueError("reconciler run not found")
        total = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM reconciler_candidates WHERE run_id = ?",
            (run_id,),
        )
        rows = await self.db.fetchall(
            "SELECT id, group_key, memory_ids_json, signal_json, input_policy_hash, "
            "status, terminal_reason, created_at, updated_at "
            "FROM reconciler_candidates WHERE run_id = ? "
            "ORDER BY created_at, id LIMIT ? OFFSET ?",
            (run_id, max(1, min(limit, 100)), max(0, offset)),
        )
        return {
            "run_id": run_id,
            "project_id": project_id,
            "total": int(total["n"]) if total else 0,
            "candidates": [
                {
                    "id": row["id"],
                    "group_key": row["group_key"],
                    "memory_ids": json.loads(row["memory_ids_json"]),
                    "signals": json.loads(row["signal_json"] or "[]"),
                    "input_policy_hash": row["input_policy_hash"],
                    "status": row["status"],
                    "terminal_reason": row["terminal_reason"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ],
        }

    async def get_candidate_detail(self, candidate_id: str, project_id: str) -> dict:
        candidate = await self.db.fetchone(
            "SELECT * FROM reconciler_candidates WHERE id = ? AND project_id = ?",
            (candidate_id, project_id),
        )
        if not candidate:
            raise ValueError("reconciler candidate not found")
        run = await self.get_run(candidate["run_id"])
        if run["project_id"] != project_id:
            raise ValueError("reconciler candidate not found")
        inputs = await self.db.fetchall(
            "SELECT * FROM reconciler_inputs WHERE run_id = ? "
            "AND memory_id IN (SELECT value FROM json_each(?)) ORDER BY memory_id",
            (candidate["run_id"], candidate["memory_ids_json"]),
        )
        proposals = await self.db.fetchall(
            "SELECT * FROM reconciler_proposals WHERE candidate_id = ? ORDER BY created_at, id",
            (candidate_id,),
        )
        results = await self.db.fetchall(
            "SELECT * FROM curated_results WHERE candidate_id = ? ORDER BY created_at, id",
            (candidate_id,),
        )
        receipts = await self.db.fetchall(
            "SELECT r.* FROM reconciler_receipts r "
            "JOIN reconciler_proposals p ON p.id = r.proposal_id "
            "WHERE p.candidate_id = ? ORDER BY r.created_at, r.id",
            (candidate_id,),
        )
        validations = await self.db.fetchall(
            "SELECT v.* FROM reconciler_validations v "
            "JOIN reconciler_proposals p ON p.id = v.proposal_id "
            "WHERE p.candidate_id = ? ORDER BY v.created_at, v.id",
            (candidate_id,),
        )
        candidate_data = dict(candidate)
        candidate_data["memory_ids"] = json.loads(candidate_data.pop("memory_ids_json"))
        candidate_data["signals"] = json.loads(
            candidate_data.pop("signal_json") or "[]"
        )
        candidate_data.pop("lease_owner", None)
        candidate_data.pop("lease_until", None)
        input_data = []
        for row in inputs:
            item = dict(row)
            item["snapshot"] = json.loads(item.pop("snapshot_json"))
            input_data.append(item)
        proposal_data = []
        for row in proposals:
            item = dict(row)
            item["claims"] = json.loads(item.pop("claims_json") or "[]")
            item["proposal"] = json.loads(item.pop("proposal_json") or "{}")
            proposal_data.append(item)
        return {
            "run": run,
            "candidate": candidate_data,
            "inputs": input_data,
            "proposals": proposal_data,
            "results": [dict(row) for row in results],
            "receipts": [
                {**dict(row), "details": json.loads(row["details_json"] or "{}")}
                for row in receipts
            ],
            "validations": [
                {**dict(row), "details": json.loads(row["details_json"] or "{}")}
                for row in validations
            ],
        }

    async def get_result_detail(self, result_id: str, project_id: str) -> dict:
        row = await self.db.fetchone(
            "SELECT cr.id, cr.project_id, cr.status, cr.revision, cr.action, "
            "cr.body, cr.representative_memory_id, cr.created_at, cr.activated_at, "
            "cr.cancelled_at, cr.stale_at, cr.stale_reason, p.proposal_json "
            "FROM curated_results cr JOIN reconciler_proposals p ON p.id = cr.proposal_id "
            "WHERE cr.id = ? AND cr.project_id = ?",
            (result_id, project_id),
        )
        if not row:
            raise ValueError("curated result not found")
        sources = await self.db.fetchall(
            "SELECT memory_id, input_hash, source_role FROM curated_sources "
            "WHERE result_id = ? ORDER BY source_role = 'representative' DESC, memory_id",
            (result_id,),
        )
        claims = await self.db.fetchall(
            "SELECT id, claim_id, text, conditions_json FROM curated_claims "
            "WHERE result_id = ? ORDER BY claim_id",
            (result_id,),
        )
        references = await self.db.fetchall(
            "SELECT claim_id, memory_id, input_hash FROM curated_claim_sources "
            "WHERE result_id = ? ORDER BY claim_id, memory_id",
            (result_id,),
        )
        references_by_claim: dict[str, list[dict]] = {}
        for reference in references:
            references_by_claim.setdefault(str(reference["claim_id"]), []).append(
                {
                    "memory_id": reference["memory_id"],
                    "input_hash": reference["input_hash"],
                }
            )
        proposal = json.loads(row["proposal_json"] or "{}")
        return {
            **{key: row[key] for key in row.keys() if key != "proposal_json"},
            "rationale": proposal.get("rationale"),
            "preserved_conditions": proposal.get("preserved_conditions", []),
            "removed_repetition": proposal.get("removed_repetition", []),
            "uncertainties": proposal.get("uncertainties", []),
            "sources": [dict(source) for source in sources],
            "claims": [
                {
                    "claim_id": claim["claim_id"],
                    "text": claim["text"],
                    "conditions": json.loads(claim["conditions_json"] or "[]"),
                    "source_refs": references_by_claim.get(str(claim["id"]), []),
                }
                for claim in claims
            ],
        }

    async def get_metrics(self, project_id: str) -> dict:
        runs = await self.db.fetchall(
            "SELECT id, status, created_at, completed_at, stats_json "
            "FROM reconciler_runs WHERE project_id = ?",
            (project_id,),
        )
        replay = await self.db.fetchone(
            "WITH inputs AS ("
            "SELECT input_policy_hash FROM reconciler_candidates WHERE project_id = ? "
            "UNION SELECT input_policy_hash FROM curated_results WHERE project_id = ?"
            "), result_counts AS ("
            "SELECT input_policy_hash, COUNT(*) AS n FROM curated_results "
            "WHERE project_id = ? GROUP BY input_policy_hash"
            "), activation_counts AS ("
            "SELECT c.input_policy_hash, COUNT(*) AS n FROM reconciler_receipts r "
            "JOIN curated_results c ON c.id = r.result_id "
            "WHERE c.project_id = ? AND r.operation = 'activation' GROUP BY c.input_policy_hash"
            ") SELECT COUNT(*) AS checked, "
            "SUM(CASE WHEN COALESCE(c.n, 0) > 1 OR COALESCE(a.n, 0) > 1 THEN 1 ELSE 0 END) AS failed, "
            "SUM(MAX(0, COALESCE(c.n, 0) - 1)) AS duplicate_results, "
            "SUM(MAX(0, COALESCE(a.n, 0) - 1)) AS duplicate_activations "
            "FROM inputs i LEFT JOIN result_counts c ON c.input_policy_hash = i.input_policy_hash "
            "LEFT JOIN activation_counts a ON a.input_policy_hash = i.input_policy_hash",
            (project_id, project_id, project_id, project_id),
        )
        statuses: dict[str, int] = {}
        durations: list[float] = []
        llm_calls = 0
        judge_failed_call_count = 0
        estimated_input_tokens = 0
        reported_usage_calls = 0
        reported_input_tokens = 0
        reported_output_tokens = 0
        reported_cache_creation_input_tokens = 0
        reported_cache_read_input_tokens = 0
        candidate_group_count = 0
        deduplicated_candidate_count = 0
        trend_runs = []
        for run in runs:
            status = str(run["status"])
            statuses[status] = statuses.get(status, 0) + 1
            stats = json.loads(run["stats_json"] or "{}")
            llm_calls += int(stats.get("llm_calls", 0))
            judge_failed_call_count += int(stats.get("judge_failed_calls", 0))
            estimated_input_tokens += int(stats.get("estimated_input_tokens", 0))
            reported_usage_calls += int(stats.get("reported_usage_calls", 0))
            reported_input_tokens += int(stats.get("reported_input_tokens", 0))
            reported_output_tokens += int(stats.get("reported_output_tokens", 0))
            reported_cache_creation_input_tokens += int(
                stats.get("reported_cache_creation_input_tokens", 0)
            )
            reported_cache_read_input_tokens += int(
                stats.get("reported_cache_read_input_tokens", 0)
            )
            candidate_group_count += int(stats.get("candidate_group_count", 0))
            deduplicated_candidate_count += int(
                stats.get("deduplicated_candidate_count", 0)
            )
            if run["completed_at"]:
                started = datetime.fromisoformat(
                    str(run["created_at"]).replace("Z", "+00:00")
                )
                completed = datetime.fromisoformat(
                    str(run["completed_at"]).replace("Z", "+00:00")
                )
                durations.append(max(0.0, (completed - started).total_seconds()))
                if status in {
                    "completed",
                    "partial_success",
                    "failed",
                    "needs_approval",
                }:
                    trend_runs.append((completed.timestamp(), str(run["id"]), stats))
        durations.sort()
        trend_runs.sort(key=lambda item: (item[0], item[1]), reverse=True)
        run_trends = {
            "window_runs": METRIC_TREND_WINDOW_RUNS,
            "ready": False,
            "recent": None,
            "previous": None,
        }
        trend_alerts = []
        budget_rows = await self.db.fetchall(
            "SELECT DISTINCT run_id FROM reconciler_candidates WHERE project_id = ? AND terminal_reason LIKE '%activation budget exceeded%'",
            (project_id,),
        )
        budget_run_ids = {str(row["run_id"]) for row in budget_rows}
        recent_budget_run_count = sum(
            run_id in budget_run_ids
            for _, run_id, _ in trend_runs[:METRIC_TREND_WINDOW_RUNS]
        )
        if recent_budget_run_count >= 2:
            trend_alerts.append(
                {"kind": "activation_budget_repeated", "count": recent_budget_run_count}
            )
        if len(trend_runs) >= 2 * METRIC_TREND_WINDOW_RUNS:
            risk_rows = await self.db.fetchall(
                "SELECT run_id, COUNT(*) AS total, "
                "SUM(CASE WHEN lower(trim(json_extract(proposal_json, '$.risk'))) IN ('low', 'medium', 'high', 'critical') THEN 1 ELSE 0 END) AS classified, "
                "SUM(CASE WHEN lower(trim(json_extract(proposal_json, '$.risk'))) IN ('high', 'critical') THEN 1 ELSE 0 END) AS high "
                "FROM reconciler_proposals WHERE project_id = ? GROUP BY run_id",
                (project_id,),
            )
            risk_by_run = {str(row["run_id"]): row for row in risk_rows}
            for label, selected in (
                ("recent", trend_runs[:METRIC_TREND_WINDOW_RUNS]),
                (
                    "previous",
                    trend_runs[METRIC_TREND_WINDOW_RUNS : 2 * METRIC_TREND_WINDOW_RUNS],
                ),
            ):
                call_count = sum(
                    int(stats.get("llm_calls", 0)) for _, _, stats in selected
                )
                failed_calls = sum(
                    int(stats.get("judge_failed_calls", 0)) for _, _, stats in selected
                )
                risk_samples = [
                    risk_by_run[run_id]
                    for _, run_id, _ in selected
                    if run_id in risk_by_run
                ]
                total_proposals = sum(int(row["total"]) for row in risk_samples)
                classified_proposals = sum(
                    int(row["classified"]) for row in risk_samples
                )
                high_risk_proposals = sum(int(row["high"]) for row in risk_samples)
                run_trends[label] = {
                    "run_ids": [run_id for _, run_id, _ in selected],
                    "llm_calls": call_count,
                    "judge_failed_calls": failed_calls,
                    "judge_failure_rate": (
                        failed_calls / call_count if call_count else None
                    ),
                    "proposal_count": total_proposals,
                    "classified_proposal_count": classified_proposals,
                    "high_risk_proposal_count": high_risk_proposals,
                    "high_risk_proposal_rate": (
                        high_risk_proposals / classified_proposals
                        if classified_proposals
                        else None
                    ),
                    "risk_classification_coverage": (
                        classified_proposals / total_proposals
                        if total_proposals
                        else None
                    ),
                    "activation_budget_run_count": sum(
                        run_id in budget_run_ids for _, run_id, _ in selected
                    ),
                }
            run_trends["ready"] = True
            recent = run_trends["recent"]
            previous = run_trends["previous"]
            for field, kind, count_field in (
                ("judge_failure_rate", "judge_failure_increase", "judge_failed_calls"),
                (
                    "high_risk_proposal_rate",
                    "high_risk_proposal_increase",
                    "high_risk_proposal_count",
                ),
            ):
                if (
                    recent[field] is not None
                    and previous[field] is not None
                    and recent[field] > previous[field]
                ):
                    trend_alerts.append({"kind": kind, "count": recent[count_field]})
        anchor_events = await self.db.fetchall(
            "SELECT status, details_json, created_at FROM reconciler_validations "
            "WHERE stage = 'anchor_status' AND json_extract(details_json, '$.project_id') = ? ORDER BY rowid",
            (project_id,),
        )
        anchor_open: dict[str, Optional[datetime]] = {}
        anchor_durations: list[float] = []
        anchor_unmeasured = 0
        anchor_timing_errors = 0
        for event in anchor_events:
            details = json.loads(event["details_json"])
            memory_id = details["memory_id"]
            try:
                reported_at = datetime.fromisoformat(
                    str(event["created_at"]).replace("Z", "+00:00")
                )
                reported_at = reported_at.replace(
                    tzinfo=reported_at.tzinfo or timezone.utc
                )
            except ValueError:
                reported_at = None
                anchor_timing_errors += 1
            if event["status"] == "stale":
                anchor_open.setdefault(memory_id, reported_at)
            elif event["status"] == "fresh":
                if memory_id in anchor_open:
                    started_at = anchor_open.pop(memory_id)
                    if started_at is not None and reported_at is not None:
                        elapsed = (reported_at - started_at).total_seconds()
                        if elapsed >= 0:
                            anchor_durations.append(elapsed)
                        else:
                            anchor_unmeasured += 1
                            anchor_timing_errors += 1
                    else:
                        anchor_unmeasured += 1
                elif details.get("from_status") == "stale":
                    anchor_unmeasured += 1
        anchor_durations.sort()
        anchor_open_ages = []
        for started_at in anchor_open.values():
            if started_at is not None:
                age = _epoch() - started_at.timestamp()
                if age >= 0:
                    anchor_open_ages.append(age)
                else:
                    anchor_timing_errors += 1
        candidate_count = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM reconciler_candidates WHERE project_id = ?",
            (project_id,),
        )
        candidate_issues = await self.db.fetchone(
            "SELECT SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
            "SUM(CASE WHEN terminal_reason LIKE '%budget exceeded' THEN 1 ELSE 0 END) AS budget_exceeded "
            "FROM reconciler_candidates WHERE project_id = ?",
            (project_id,),
        )
        actions = await self.db.fetchall(
            "SELECT action, COUNT(*) AS n FROM reconciler_proposals "
            "WHERE project_id = ? GROUP BY action",
            (project_id,),
        )
        review_reasons = await self.db.fetchall(
            "SELECT COALESCE(json_extract(proposal_json, '$.review_reason'), 'unclassified') AS reason, COUNT(*) AS n "
            "FROM reconciler_proposals WHERE project_id = ? AND status = 'needs_review' "
            "GROUP BY reason",
            (project_id,),
        )
        review_reason_counts = {
            str(row["reason"]): int(row["n"]) for row in review_reasons
        }
        unresolved_contradiction_count = review_reason_counts.get("contradiction", 0)
        results = await self.db.fetchall(
            "SELECT status, COUNT(*) AS n FROM curated_results "
            "WHERE project_id = ? GROUP BY status",
            (project_id,),
        )
        validations = await self.db.fetchone(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN v.status = 'failed' THEN 1 ELSE 0 END) AS failed, "
            "SUM(CASE WHEN v.status = 'failed' AND ("
            "lower(COALESCE(json_extract(v.details_json, '$.error'), '')) LIKE '%embedding%' "
            "OR lower(COALESCE(json_extract(v.details_json, '$.error'), '')) LIKE '%index%'"
            ") THEN 1 ELSE 0 END) AS index_failed "
            "FROM reconciler_validations v "
            "JOIN reconciler_proposals p ON p.id = v.proposal_id "
            "WHERE p.project_id = ?",
            (project_id,),
        )
        activation = await self.db.fetchone(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN r.actor = 'auto' THEN 1 ELSE 0 END) AS automatic "
            "FROM reconciler_receipts r "
            "JOIN reconciler_proposals p ON p.id = r.proposal_id "
            "WHERE p.project_id = ? AND r.operation = 'activation'",
            (project_id,),
        )
        cancellations = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM reconciler_receipts r "
            "JOIN curated_results c ON c.id = r.result_id "
            "WHERE c.project_id = ? AND r.operation = 'cancellation'",
            (project_id,),
        )
        automatic_rollbacks = await self.db.fetchone(
            "SELECT COUNT(DISTINCT activated.result_id) AS n "
            "FROM reconciler_receipts activated "
            "JOIN reconciler_receipts cancelled ON cancelled.result_id = activated.result_id "
            "JOIN curated_results c ON c.id = activated.result_id "
            "WHERE c.project_id = ? AND activated.operation = 'activation' "
            "AND activated.actor = 'auto' AND cancelled.operation = 'cancellation'",
            (project_id,),
        )
        canonical_total = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM memories WHERE project_id = ? "
            "AND COALESCE(status, 'canonical') = 'canonical'",
            (project_id,),
        )
        covered_canonical = await self.db.fetchone(
            "SELECT COUNT(DISTINCT s.memory_id) AS n FROM curated_sources s "
            "JOIN curated_results c ON c.id = s.result_id "
            "JOIN memories m ON m.id = s.memory_id "
            "WHERE c.project_id = ? AND c.status = 'active' "
            "AND c.action IN ('merge', 'supersede') AND m.project_id = ? "
            "AND COALESCE(m.status, 'canonical') = 'canonical'",
            (project_id, project_id),
        )
        claim_coverage = await self.db.fetchone(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN EXISTS ("
            "SELECT 1 FROM curated_claim_sources cs "
            "JOIN curated_sources src ON src.result_id = cs.result_id "
            "AND src.memory_id = cs.memory_id AND src.input_hash = cs.input_hash "
            "JOIN memories m ON m.id = cs.memory_id AND m.project_id = c.project_id "
            "WHERE cs.claim_id = cl.id AND cs.result_id = c.id"
            ") THEN 1 ELSE 0 END) AS covered "
            "FROM curated_claims cl JOIN curated_results c ON c.id = cl.result_id "
            "WHERE c.project_id = ? AND c.status = 'active'",
            (project_id,),
        )
        orphan_relations = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM curated_relations rel "
            "JOIN curated_results c ON c.id = rel.result_id "
            "LEFT JOIN memories source ON source.id = rel.source_id "
            "LEFT JOIN memories target ON target.id = rel.target_id "
            "WHERE c.project_id = ? AND c.status = 'active' AND rel.active = 1 "
            "AND (source.id IS NULL OR target.id IS NULL "
            "OR source.project_id != c.project_id OR target.project_id != c.project_id)",
            (project_id,),
        )
        approvals = await self.db.fetchall(
            "SELECT created_at, decision_at FROM reconciler_proposals "
            "WHERE project_id = ? AND decision_actor = 'operator' "
            "AND decision_at IS NOT NULL",
            (project_id,),
        )
        manual_decisions = await self.db.fetchone(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected "
            "FROM reconciler_proposals WHERE project_id = ? "
            "AND decision_actor = 'operator' AND decision_at IS NOT NULL",
            (project_id,),
        )
        approval_waits = sorted(
            max(
                0.0,
                (
                    datetime.fromisoformat(
                        str(row["decision_at"]).replace("Z", "+00:00")
                    )
                    - datetime.fromisoformat(
                        str(row["created_at"]).replace("Z", "+00:00")
                    )
                ).total_seconds(),
            )
            for row in approvals
        )
        manual_decision_count = int(manual_decisions["total"])
        manual_rejection_count = int(manual_decisions["rejected"] or 0)
        validation_count = int(validations["total"])
        validation_failure_count = int(validations["failed"] or 0)
        index_validation_failure_count = int(validations["index_failed"] or 0)
        activation_count = int(activation["total"])
        automatic_activation_count = int(activation["automatic"] or 0)
        cancellation_count = int(cancellations["n"])
        automatic_rollback_count = int(automatic_rollbacks["n"])
        canonical_count = int(canonical_total["n"])
        covered_count = int(covered_canonical["n"])
        claim_count = int(claim_coverage["total"])
        covered_claim_count = int(claim_coverage["covered"] or 0)
        uncovered_claim_count = claim_count - covered_claim_count
        orphan_relation_count = int(orphan_relations["n"])
        replay_checked_count = int(replay["checked"])
        replay_failed_count = int(replay["failed"] or 0)
        failed_candidate_count = int(candidate_issues["failed"] or 0)
        budget_exceeded_candidate_count = int(candidate_issues["budget_exceeded"] or 0)
        stale_result_count = next(
            (int(row["n"]) for row in results if row["status"] == "stale"), 0
        )
        alerts = [
            {"kind": kind, "count": count}
            for kind, count in (
                ("validation_failure", validation_failure_count),
                ("automatic_rollback", automatic_rollback_count),
                ("budget_exceeded", budget_exceeded_candidate_count),
                ("candidate_failure", failed_candidate_count),
                ("index_validation_failure", index_validation_failure_count),
                ("stale_result", stale_result_count),
                ("provenance_gap", uncovered_claim_count),
                ("orphan_relation", orphan_relation_count),
                ("replay_non_idempotency", replay_failed_count),
                ("unresolved_contradiction", unresolved_contradiction_count),
                ("stale_anchor", len(anchor_open)),
            )
            if count
        ]
        terminal_outcome_run_count = sum(
            statuses.get(status, 0)
            for status in ("completed", "partial_success", "failed")
        )
        alerts.extend(trend_alerts)
        return {
            "project_id": project_id,
            "run_count": len(runs),
            "runs_by_status": statuses,
            "run_trends": run_trends,
            "recent_activation_budget_run_count": recent_budget_run_count,
            "terminal_outcome_run_count": terminal_outcome_run_count,
            "run_outcome_rates": {
                status: (
                    statuses.get(status, 0) / terminal_outcome_run_count
                    if terminal_outcome_run_count
                    else None
                )
                for status in ("completed", "partial_success", "failed")
            },
            "candidate_count": int(candidate_count["n"]),
            "candidate_group_count": candidate_group_count,
            "deduplicated_candidate_count": deduplicated_candidate_count,
            "replay_checked_input_count": replay_checked_count,
            "replay_non_idempotent_input_count": replay_failed_count,
            "replay_non_idempotency_rate": (
                replay_failed_count / replay_checked_count
                if replay_checked_count
                else None
            ),
            "replay_duplicate_result_count": int(replay["duplicate_results"] or 0),
            "replay_duplicate_activation_count": int(
                replay["duplicate_activations"] or 0
            ),
            "failed_candidate_count": failed_candidate_count,
            "review_reason_counts": review_reason_counts,
            "unresolved_contradiction_count": unresolved_contradiction_count,
            "unclassified_review_count": review_reason_counts.get("unclassified", 0),
            "anchor_open_episode_count": len(anchor_open),
            "anchor_oldest_open_seconds": (
                max(anchor_open_ages) if anchor_open_ages else None
            ),
            "anchor_resolution_unmeasured_count": anchor_unmeasured,
            "anchor_timing_error_count": anchor_timing_errors,
            "anchor_resolution_seconds": {
                "count": len(anchor_durations),
                "average": (
                    sum(anchor_durations) / len(anchor_durations)
                    if anchor_durations
                    else None
                ),
                "p95": (
                    anchor_durations[ceil(len(anchor_durations) * 0.95) - 1]
                    if anchor_durations
                    else None
                ),
            },
            "budget_exceeded_candidate_count": budget_exceeded_candidate_count,
            "alerts": alerts,
            "canonical_count": canonical_count,
            "stored_active_covered_canonical_count": covered_count,
            "uncovered_canonical_count": max(0, canonical_count - covered_count),
            "active_claim_count": claim_count,
            "covered_claim_count": covered_claim_count,
            "provenance_coverage": (
                covered_claim_count / claim_count if claim_count else None
            ),
            "orphan_relation_count": orphan_relation_count,
            "llm_calls": llm_calls,
            "judge_failed_call_count": judge_failed_call_count,
            "judge_call_failure_rate": (
                judge_failed_call_count / llm_calls if llm_calls else None
            ),
            "estimated_input_tokens": estimated_input_tokens,
            "reported_usage_calls": reported_usage_calls,
            "unreported_usage_calls": max(0, llm_calls - reported_usage_calls),
            "reported_usage_coverage": (
                reported_usage_calls / llm_calls if llm_calls else None
            ),
            "reported_input_tokens": reported_input_tokens,
            "reported_output_tokens": reported_output_tokens,
            "reported_cache_creation_input_tokens": reported_cache_creation_input_tokens,
            "reported_cache_read_input_tokens": reported_cache_read_input_tokens,
            "proposal_actions": {str(row["action"]): int(row["n"]) for row in actions},
            "curated_results_by_status": {
                str(row["status"]): int(row["n"]) for row in results
            },
            "active_result_count": next(
                (int(row["n"]) for row in results if row["status"] == "active"),
                0,
            ),
            "validation_count": validation_count,
            "validation_failure_count": validation_failure_count,
            "index_validation_failure_count": index_validation_failure_count,
            "validation_failure_rate": (
                validation_failure_count / validation_count
                if validation_count
                else None
            ),
            "activation_count": activation_count,
            "cancellation_count": cancellation_count,
            "cancellation_rate": (
                cancellation_count / activation_count if activation_count else None
            ),
            "automatic_activation_count": automatic_activation_count,
            "automatic_rollback_count": automatic_rollback_count,
            "automatic_rollback_rate": (
                automatic_rollback_count / automatic_activation_count
                if automatic_activation_count
                else None
            ),
            "automatic_activation_rate": (
                automatic_activation_count / activation_count
                if activation_count
                else None
            ),
            "manual_decision_count": manual_decision_count,
            "manual_rejection_count": manual_rejection_count,
            "manual_rejection_rate": (
                manual_rejection_count / manual_decision_count
                if manual_decision_count
                else None
            ),
            "approval_wait_seconds": {
                "average": (
                    sum(approval_waits) / len(approval_waits)
                    if approval_waits
                    else None
                ),
                "p95": (
                    approval_waits[ceil(0.95 * len(approval_waits)) - 1]
                    if approval_waits
                    else None
                ),
            },
            "duration_seconds": {
                "average": sum(durations) / len(durations) if durations else None,
                "p95": (
                    durations[ceil(0.95 * len(durations)) - 1] if durations else None
                ),
            },
        }

    async def list_proposals(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        conditions = []
        params: List[Any] = []
        if project_id:
            conditions.append("p.project_id = ?")
            params.append(project_id)
        if status:
            conditions.append("p.status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(max(1, min(limit, 200)))
        rows = await self.db.fetchall(
            "SELECT p.*, cr.status AS result_status, cr.revision AS result_revision, "
            "(SELECT json_group_array(json_object('memory_id', i.memory_id, 'input_hash', i.input_hash)) "
            "FROM reconciler_inputs i WHERE i.run_id = p.run_id "
            "AND i.memory_id IN (SELECT value FROM json_each(c.memory_ids_json))) AS input_sources_json "
            "FROM reconciler_proposals p "
            "JOIN reconciler_candidates c ON c.id = p.candidate_id "
            "LEFT JOIN curated_results cr ON cr.id = p.result_id"
            + where
            + " ORDER BY p.created_at DESC LIMIT ?",
            tuple(params),
        )
        return [dict(row) for row in rows]

    async def decide_proposal(
        self, proposal_id: str, decision: str, expected_revision: int
    ) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM reconciler_proposals WHERE id = ?", (proposal_id,)
        )
        if not row:
            raise ValueError("reconciler proposal not found")
        normalized = decision.strip().lower()
        if normalized not in {
            "approve",
            "approved",
            "activate",
            "reject",
            "rejected",
            "deny",
        }:
            raise ValueError("decision must be approve or reject")
        if row["status"] in {"applied", "rejected"}:
            same_decision = (
                row["status"] == "applied"
                and normalized in {"approve", "approved", "activate"}
            ) or (
                row["status"] == "rejected"
                and normalized in {"reject", "rejected", "deny"}
            )
            if same_decision:
                return dict(row)
            raise ReconcilerConflictError("proposal already decided")
        if int(row["expected_revision"]) != int(expected_revision):
            raise ReconcilerConflictError("proposal revision is stale")
        await self._ensure_mutation_allowed()
        run = await self.db.fetchone(
            "SELECT dry_run, status, policy_hash, detector_version FROM reconciler_runs WHERE id = ?",
            (row["run_id"],),
        )
        if run and run["status"] == "cancelled":
            raise ReconcilerValidationError("reconciler run was cancelled")
        if run and bool(run["dry_run"]):
            raise ReconcilerValidationError("dry-run proposals are preview-only")
        if row["status"] != "needs_approval":
            raise ReconcilerValidationError(
                "only needs_approval proposals can be approved or rejected"
            )
        if normalized in {"reject", "rejected", "deny"}:
            now = _now()
            async with self.db.transaction():
                changed = await self.db.execute(
                    "UPDATE reconciler_proposals SET status = 'rejected', decision = ?, decision_actor = 'operator', expected_revision = expected_revision + 1, decision_at = ?, updated_at = ? WHERE id = ? AND expected_revision = ? AND status = 'needs_approval'",
                    (normalized, now, now, proposal_id, expected_revision),
                )
                if changed.rowcount != 1:
                    raise ReconcilerConflictError("proposal revision is stale")
                await self.db.execute(
                    "INSERT INTO reconciler_receipts(id, proposal_id, operation, from_status, to_status, revision, actor, details_json, created_at) VALUES (?, ?, 'decision', ?, 'rejected', ?, 'operator', '{}', ?)",
                    (
                        "rrc_" + uuid4().hex,
                        proposal_id,
                        row["status"],
                        int(expected_revision) + 1,
                        now,
                    ),
                )
            await self._finish_run_if_ready(row["run_id"])
            return dict(
                await self.db.fetchone(
                    "SELECT * FROM reconciler_proposals WHERE id = ?", (proposal_id,)
                )
            )
        return await self._activate_proposal(
            proposal_id, expected_revision, actor="operator"
        )

    async def _activate_proposal(
        self, proposal_id: str, expected_revision: int, actor: str
    ) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM reconciler_proposals WHERE id = ?", (proposal_id,)
        )
        if not row:
            raise ValueError("reconciler proposal not found")
        if int(row["expected_revision"]) != int(expected_revision):
            raise ReconcilerConflictError("proposal revision is stale")
        await self._ensure_mutation_allowed()
        if row["status"] == "applied" and row["result_id"]:
            return {
                "proposal_id": proposal_id,
                "result_id": row["result_id"],
                "status": "active",
            }
        if row["status"] != "needs_approval":
            raise ReconcilerValidationError(
                "only needs_approval proposals can be activated"
            )
        run = await self.db.fetchone(
            "SELECT dry_run, status, policy_hash, detector_version, budget_json FROM reconciler_runs WHERE id = ?",
            (row["run_id"],),
        )
        if not run:
            raise ReconcilerValidationError("reconciler run not found")
        try:
            budget = json.loads(run["budget_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise ReconcilerValidationError(
                "invalid run activation budget; start a new run", budget="activations"
            ) from exc
        activation_limit = (
            budget.get("max_activations") if isinstance(budget, dict) else None
        )
        if type(activation_limit) is not int or activation_limit < 0:
            raise ReconcilerValidationError(
                "invalid run activation budget; start a new run", budget="activations"
            )
        if run and run["status"] == "cancelled":
            raise ReconcilerValidationError("reconciler run was cancelled")
        if run and bool(run["dry_run"]):
            raise ReconcilerValidationError("dry-run proposals are preview-only")
        if run and run["detector_version"] != DETECTOR_VERSION:
            raise ReconcilerConflictError(
                "run detector changed before activation; start a new run"
            )
        if (
            run
            and _hash((await self._policy(row["project_id"])).model_dump())
            != run["policy_hash"]
        ):
            raise ReconcilerConflictError(
                "run policy changed before activation; start a new run"
            )
        claims = json.loads(row["claims_json"] or "[]")
        payload = json.loads(row["proposal_json"] or "{}")
        candidate = await self.db.fetchone(
            "SELECT memory_ids_json FROM reconciler_candidates WHERE id = ?",
            (row["candidate_id"],),
        )
        source_ids = (
            sorted(json.loads(candidate["memory_ids_json"])) if candidate else []
        )
        if not source_ids:
            source_ids = [row["representative_memory_id"]]
        current_hashes = {}
        for memory_id in source_ids:
            current_hashes[memory_id] = await self.effective_read.current_input_hash(
                memory_id
            )
        expected_hashes = {
            ref["memory_id"]: ref["input_hash"]
            for claim in claims
            for ref in claim.get("source_refs", [])
        }
        input_rows = await self.db.fetchall(
            "SELECT memory_id, input_hash FROM reconciler_inputs WHERE run_id = ? AND memory_id IN (SELECT value FROM json_each(?))",
            (row["run_id"], json.dumps(source_ids)),
        )
        expected_hashes.update(
            {item["memory_id"]: item["input_hash"] for item in input_rows}
        )
        if any(
            current_hashes.get(memory_id) != expected_hashes.get(memory_id)
            for memory_id in source_ids
        ):
            await self.db.execute(
                "UPDATE reconciler_proposals SET status = 'stale', error = 'canonical input hash changed', updated_at = ? WHERE id = ?",
                (_now(), proposal_id),
            )
            raise ReconcilerValidationError("canonical input hash changed")
        placeholders = ",".join("?" for _ in source_ids)
        replacing_action = row["action"] not in {"add_relation", "mark_stale"}
        overlap_sql = (
            "SELECT cr.id FROM curated_results cr "
            "JOIN curated_sources cs ON cs.result_id = cr.id "
            "WHERE cr.status = 'active' "
            "AND cr.action NOT IN ('add_relation', 'mark_stale') "
            f"AND cs.memory_id IN ({placeholders}) LIMIT 1"
        )
        overlap = (
            await self.db.fetchone(overlap_sql, tuple(source_ids))
            if replacing_action
            else None
        )
        if overlap:
            await self.db.execute(
                "UPDATE reconciler_proposals SET status = 'conflict', error = 'active source overlap', updated_at = ? WHERE id = ?",
                (_now(), proposal_id),
            )
            raise ReconcilerConflictError("source overlaps an active curated result")
        result_id = make_curated_id(proposal_id)
        now = _now()
        activation_revision = int(expected_revision) + 1
        body = str(row["body"] or "") or str(payload.get("body") or "")
        if not body:
            raise ReconcilerValidationError("curated body is empty")
        activation_count = await self.db.fetchone(
            "SELECT COUNT(*) AS count FROM reconciler_receipts r JOIN reconciler_proposals rp ON rp.id = r.proposal_id WHERE rp.run_id = ? AND r.operation = 'activation'",
            (row["run_id"],),
        )
        if activation_count and int(activation_count["count"]) >= activation_limit:
            raise ReconcilerValidationError(
                "activation budget exceeded", budget="activations"
            )
        index_error = None
        stale_inside = False
        overlap_inside = False
        try:
            async with self.db.transaction():
                current_run = await self.db.fetchone(
                    "SELECT status FROM reconciler_runs WHERE id = ?", (row["run_id"],)
                )
                if current_run and current_run["status"] == "cancelled":
                    raise ReconcilerValidationError("reconciler run was cancelled")
                current_hashes = {
                    memory_id: await self.effective_read.current_input_hash(memory_id)
                    for memory_id in source_ids
                }
                if any(
                    current_hashes.get(memory_id) != expected_hashes.get(memory_id)
                    for memory_id in source_ids
                ):
                    stale_inside = True
                    raise ReconcilerValidationError("canonical input hash changed")
                overlap = (
                    await self.db.fetchone(overlap_sql, tuple(source_ids))
                    if replacing_action
                    else None
                )
                if overlap:
                    overlap_inside = True
                    raise ReconcilerConflictError(
                        "source overlaps an active curated result"
                    )
                proposed_dependencies = [
                    relation
                    for relation in payload.get("relations") or []
                    if relation.get("relation_type") == "depends_on"
                ]
                if proposed_dependencies:
                    active_dependencies = await self.db.fetchall(
                        "SELECT r.source_id, r.target_id FROM curated_relations r "
                        "JOIN curated_results cr ON cr.id = r.result_id "
                        "WHERE cr.project_id = ? AND cr.status = 'active' "
                        "AND r.active = 1 AND r.relation_type = 'depends_on'",
                        (row["project_id"],),
                    )
                    dependencies: dict[str, set[str]] = {}
                    for relation in list(active_dependencies) + proposed_dependencies:
                        source_id = str(relation["source_id"])
                        target_id = str(relation["target_id"])
                        dependencies.setdefault(source_id, set()).add(target_id)
                        dependencies.setdefault(target_id, set())
                    remaining = set(dependencies)
                    while remaining:
                        ready = {
                            memory_id
                            for memory_id in remaining
                            if not (dependencies[memory_id] & remaining)
                        }
                        if not ready:
                            raise ReconcilerValidationError("derived dependency cycle")
                        remaining -= ready
                activation_count = await self.db.fetchone(
                    "SELECT COUNT(*) AS count FROM reconciler_receipts r JOIN reconciler_proposals rp ON rp.id = r.proposal_id WHERE rp.run_id = ? AND r.operation = 'activation'",
                    (row["run_id"],),
                )
                if (
                    activation_count
                    and int(activation_count["count"]) >= activation_limit
                ):
                    raise ReconcilerValidationError(
                        "activation budget exceeded", budget="activations"
                    )
                cas = await self.db.execute(
                    "UPDATE reconciler_proposals SET status = 'applying', decision = 'approve', updated_at = ? WHERE id = ? AND expected_revision = ? AND status = 'needs_approval'",
                    (now, proposal_id, expected_revision),
                )
                if cas.rowcount != 1:
                    raise ReconcilerConflictError("proposal revision is stale")
                await self.db.execute(
                    "INSERT INTO curated_results(id, proposal_id, candidate_id, project_id, representative_memory_id, body, action, status, revision, input_policy_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'inactive', 0, ?, ?)",
                    (
                        result_id,
                        proposal_id,
                        row["candidate_id"],
                        row["project_id"],
                        row["representative_memory_id"],
                        body,
                        row["action"],
                        row["input_policy_hash"],
                        now,
                    ),
                )
                for memory_id in source_ids:
                    await self.db.execute(
                        "INSERT INTO curated_sources(result_id, memory_id, input_hash, source_role) VALUES (?, ?, ?, ?)",
                        (
                            result_id,
                            memory_id,
                            expected_hashes[memory_id],
                            (
                                "representative"
                                if memory_id == row["representative_memory_id"]
                                else "source"
                            ),
                        ),
                    )
                for claim in claims:
                    claim_row_id = "cc_" + uuid4().hex
                    await self.db.execute(
                        "INSERT INTO curated_claims(id, result_id, claim_id, text, conditions_json) VALUES (?, ?, ?, ?, ?)",
                        (
                            claim_row_id,
                            result_id,
                            claim["claim_id"],
                            claim["text"],
                            canonical_json(claim.get("conditions") or []),
                        ),
                    )
                    for ref in claim.get("source_refs", []):
                        await self.db.execute(
                            "INSERT INTO curated_claim_sources(claim_id, result_id, memory_id, input_hash) VALUES (?, ?, ?, ?)",
                            (
                                claim_row_id,
                                result_id,
                                ref["memory_id"],
                                ref["input_hash"],
                            ),
                        )
                for relation in payload.get("relations") or []:
                    await self.db.execute(
                        "INSERT INTO curated_relations(id, result_id, source_id, target_id, relation_type, active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                        (
                            "crr_" + uuid4().hex,
                            result_id,
                            relation["source_id"],
                            relation["target_id"],
                            relation["relation_type"],
                            now,
                        ),
                    )
                try:
                    await self._write_indexes(
                        result_id,
                        body,
                        row["project_id"],
                    )
                except Exception as exc:
                    index_error = exc
                    await self.db.execute(
                        "UPDATE curated_results SET status = 'inactive', stale_reason = ? WHERE id = ?",
                        (str(exc)[:1000], result_id),
                    )
                    await self.db.execute(
                        "UPDATE reconciler_proposals SET status = 'needs_review', error = ?, updated_at = ? WHERE id = ?",
                        (str(exc)[:1000], now, proposal_id),
                    )
                    await self.db.execute(
                        "INSERT INTO reconciler_validations(id, proposal_id, result_id, stage, status, details_json, created_at) VALUES (?, ?, ?, 'activation', 'failed', ?, ?)",
                        (
                            "rv_" + uuid4().hex,
                            proposal_id,
                            result_id,
                            canonical_json({"error": str(exc)}),
                            now,
                        ),
                    )
                if index_error is None:
                    if (
                        _hash((await self._policy(row["project_id"])).model_dump())
                        != run["policy_hash"]
                    ):
                        raise ReconcilerConflictError(
                            "run policy changed before activation; start a new run"
                        )
                    await self.db.execute(
                        "UPDATE curated_results SET status = 'active', revision = 1, activated_at = ? WHERE id = ?",
                        (now, result_id),
                    )
                    await self.db.execute(
                        "UPDATE reconciler_proposals SET status = 'applied', decision_actor = ?, decision_at = ?, result_id = ?, updated_at = ? WHERE id = ? AND status = 'applying'",
                        (actor, now, result_id, now, proposal_id),
                    )
                    await self.db.execute(
                        "INSERT INTO reconciler_receipts(id, proposal_id, result_id, operation, from_status, to_status, revision, actor, details_json, created_at) VALUES (?, ?, ?, 'activation', ?, 'active', ?, ?, '{}', ?)",
                        (
                            "rrc_" + uuid4().hex,
                            proposal_id,
                            result_id,
                            row["status"],
                            activation_revision,
                            actor,
                            now,
                        ),
                    )
                    await self.db.execute(
                        "INSERT INTO reconciler_validations(id, proposal_id, result_id, stage, status, details_json, created_at) VALUES (?, ?, ?, 'activation', 'passed', '{}', ?)",
                        ("rv_" + uuid4().hex, proposal_id, result_id, now),
                    )
                    await self.effective_read.bump_read_revision("activation")
        except ReconcilerConflictError:
            if overlap_inside:
                await self.db.execute(
                    "UPDATE reconciler_proposals SET status = 'conflict', error = 'active source overlap', updated_at = ? WHERE id = ?",
                    (_now(), proposal_id),
                )
            raise
        except Exception as exc:
            if stale_inside:
                await self.db.execute(
                    "UPDATE reconciler_proposals SET status = 'stale', error = 'canonical input hash changed', updated_at = ? WHERE id = ?",
                    (_now(), proposal_id),
                )
                raise
            current_run = await self.db.fetchone(
                "SELECT status FROM reconciler_runs WHERE id = ?", (row["run_id"],)
            )
            if current_run and current_run["status"] == "cancelled":
                raise
            await self.db.execute(
                "UPDATE reconciler_proposals SET status = 'needs_review', error = ?, updated_at = ? WHERE id = ?",
                (str(exc)[:1000], _now(), proposal_id),
            )
            try:
                await self.db.execute(
                    "INSERT INTO reconciler_validations(id, proposal_id, result_id, stage, status, details_json, created_at) VALUES (?, ?, ?, 'activation', 'failed', ?, ?)",
                    (
                        "rv_" + uuid4().hex,
                        proposal_id,
                        result_id,
                        canonical_json({"error": str(exc)}),
                        _now(),
                    ),
                )
            except Exception:
                logger.exception("Failed to record activation validation")
            raise
        if index_error is not None:
            raise ReconcilerValidationError(f"curated index failed: {index_error}")
        await self._finish_candidate(row["candidate_id"], "completed", "activated")
        return {
            "proposal_id": proposal_id,
            "result_id": result_id,
            "status": "active",
            "revision": 1,
        }

    async def _write_indexes(self, result_id: str, body: str, project_id: str) -> None:
        import numpy as np

        if self.embedding_service is None:
            raise ReconcilerValidationError(
                "embedding service is required for curated result activation"
            )
        model_name = str(getattr(self.embedding_service, "model_name", "") or "")
        if not model_name:
            raise ReconcilerValidationError("curated embedding model is unknown")
        dimension = int(self.embedding_service.dimension)
        if dimension != self.db.embedding_dim:
            raise ReconcilerValidationError(
                "curated embedding dimension differs from the active database model"
            )
        stored_model = await self.db.get_embedding_metadata(
            "reconciler_embedding_model"
        )
        stored_dimension = await self.db.get_embedding_metadata(
            "reconciler_embedding_dimension"
        )
        if stored_model and model_name and stored_model != model_name:
            raise ReconcilerValidationError(
                "reconciler embedding model is incompatible with the active index"
            )
        if stored_dimension and int(stored_dimension) != dimension:
            raise ReconcilerValidationError(
                "reconciler embedding dimension is incompatible with the active index"
            )
        if not stored_model:
            unversioned = await self.db.fetchone(
                "SELECT COUNT(*) AS count FROM curated_results WHERE status = 'active'"
            )
            if unversioned and unversioned["count"]:
                raise ReconcilerValidationError(
                    "active curated vectors require reindex before activation"
                )
        for key, value in (
            ("reconciler_embedding_model", model_name),
            ("reconciler_embedding_dimension", str(dimension)),
        ):
            if value and not await self.db.get_embedding_metadata(key):
                await self.db.execute(
                    "INSERT INTO embedding_metadata(key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (key, value, _now()),
                )
        await self.db.execute(
            "DELETE FROM curated_results_fts WHERE result_id = ?", (result_id,)
        )
        await self.db.execute(
            "INSERT INTO curated_results_fts(result_id, body, project_id) VALUES (?, ?, ?)",
            (result_id, body, project_id),
        )
        vector = await self.embedding_service.aembed(body)
        if len(vector) != dimension:
            raise ReconcilerValidationError(
                f"curated embedding dimension {len(vector)} does not match {dimension}"
            )
        if hasattr(self.embedding_service, "to_bytes"):
            embedding = self.embedding_service.to_bytes(vector)
        else:
            embedding = np.asarray(vector, dtype=np.float32).tobytes()
        values = np.frombuffer(embedding, dtype=np.float32)
        if values.size != dimension:
            raise ReconcilerValidationError(
                f"curated embedding bytes dimension {values.size} does not match {dimension}"
            )
        embedding = values.astype(np.float32).tobytes()
        await self.db.execute(
            "DELETE FROM curated_results_vec_fallback WHERE result_id = ?", (result_id,)
        )
        await self.db.execute(
            "INSERT INTO curated_results_vec_fallback(result_id, embedding) VALUES (?, ?)",
            (result_id, embedding),
        )
        table = "curated_results_vec_active"
        exists = await self.db.fetchone(
            "SELECT type, sql FROM sqlite_master WHERE name = ?", (table,)
        )
        if exists:
            await self.db.execute(
                f"DELETE FROM {table} WHERE result_id = ?", (result_id,)
            )
            if "USING VEC0" in str(exists["sql"] or "").upper():
                try:
                    await self.db.execute(
                        f"INSERT INTO {table}(result_id, embedding) VALUES (?, ?)",
                        (result_id, json.dumps(values.tolist())),
                    )
                except Exception as exc:
                    raise RuntimeError(f"curated vector index failed: {exc}") from exc
            else:
                await self.db.execute(
                    f"INSERT INTO {table}(result_id, embedding) VALUES (?, ?)",
                    (result_id, embedding),
                )
        errors = await self._index_errors(result_id, body, project_id)
        if errors:
            raise ReconcilerValidationError("; ".join(errors))

    async def _index_errors(
        self, result_id: str, body: str, project_id: str
    ) -> list[str]:
        errors = []
        fts_table = await self.db.fetchone(
            "SELECT name FROM sqlite_master WHERE name = 'curated_results_fts'"
        )
        fts = (
            await self.db.fetchall(
                "SELECT body, project_id FROM curated_results_fts WHERE result_id = ?",
                (result_id,),
            )
            if fts_table
            else []
        )
        if (
            len(fts) != 1
            or fts[0]["body"] != body
            or fts[0]["project_id"] != project_id
        ):
            errors.append("curated index FTS content or scope mismatch")
        model = await self.db.get_embedding_metadata("reconciler_embedding_model")
        dimension = await self.db.get_embedding_metadata(
            "reconciler_embedding_dimension"
        )
        expected_model = getattr(self.embedding_service, "model_name", None)
        if not model or (expected_model and model != expected_model):
            errors.append("curated index embedding model mismatch")
        if str(dimension) != str(self.db.embedding_dim):
            errors.append("curated index embedding dimension mismatch")
        vectors = {}
        canonical_table = await self.db.active_embedding_table()
        canonical_schema = await self.db.fetchone(
            "SELECT sql FROM sqlite_master WHERE name = ?", (canonical_table,)
        )
        require_vec = bool(
            canonical_schema
            and "USING VEC0" in str(canonical_schema["sql"] or "").upper()
        )
        for table in ("curated_results_vec_fallback", "curated_results_vec_active"):
            exists = await self.db.fetchone(
                "SELECT name, sql FROM sqlite_master WHERE name = ?", (table,)
            )
            if not exists:
                errors.append(f"curated index table {table} is missing")
                continue
            if (
                table == "curated_results_vec_active"
                and require_vec
                and "USING VEC0" not in str(exists["sql"] or "").upper()
            ):
                errors.append("curated index active table is not vec0")
            rows = await self.db.fetchall(
                f"SELECT embedding FROM {table} WHERE result_id = ?", (result_id,)
            )
            if len(rows) != 1:
                errors.append(
                    f"curated index entry in {table} is missing or duplicated"
                )
                continue
            value = rows[0]["embedding"]
            try:
                vector = (
                    np.asarray(json.loads(value), dtype=np.float32)
                    if isinstance(value, str)
                    else np.frombuffer(value, dtype=np.float32)
                )
                if (
                    vector.size != self.db.embedding_dim
                    or not np.isfinite(vector).all()
                ):
                    raise ValueError("invalid vector")
                vectors[table] = vector.tobytes()
            except (ValueError, TypeError):
                errors.append(f"curated index vector in {table} is invalid")
        if len(vectors) == 2 and len(set(vectors.values())) != 1:
            errors.append("curated index active and fallback vectors differ")
        return errors

    async def cancel_result(self, result_id: str, expected_revision: int) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM curated_results WHERE id = ?", (result_id,)
        )
        if not row:
            raise ValueError("curated result not found")
        if row["status"] == "cancelled":
            return dict(row)
        if int(row["revision"]) != int(expected_revision):
            raise ReconcilerConflictError("result revision is stale")
        now = _now()
        async with self.db.transaction():
            current = await self.db.fetchone(
                "SELECT * FROM curated_results WHERE id = ?", (result_id,)
            )
            if not current:
                raise ValueError("curated result not found")
            if current["status"] == "cancelled":
                return dict(current)
            if int(current["revision"]) != int(expected_revision):
                raise ReconcilerConflictError("result revision is stale")
            await self._ensure_mutation_allowed()
            changed = await self.db.execute(
                "UPDATE curated_results SET status = 'cancelled', cancelled_at = ?, revision = revision + 1 WHERE id = ? AND revision = ? AND status != 'cancelled'",
                (now, result_id, expected_revision),
            )
            if changed.rowcount != 1:
                raise ReconcilerConflictError("result revision is stale")
            await self.db.execute(
                "DELETE FROM curated_results_fts WHERE result_id = ?", (result_id,)
            )
            await self.db.execute(
                "DELETE FROM curated_results_vec_fallback WHERE result_id = ?",
                (result_id,),
            )
            for table in ("curated_results_vec_active", "curated_results_vec_next"):
                await self.db.execute(
                    f"DELETE FROM {table} WHERE result_id = ?", (result_id,)
                )
            await self.db.execute(
                "UPDATE curated_relations SET active = 0 WHERE result_id = ?",
                (result_id,),
            )
            await self.db.execute(
                "INSERT INTO reconciler_receipts(id, result_id, operation, from_status, to_status, revision, details_json, created_at) VALUES (?, ?, 'cancellation', ?, 'cancelled', ?, '{}', ?)",
                (
                    "rrc_" + uuid4().hex,
                    result_id,
                    current["status"],
                    int(expected_revision) + 1,
                    now,
                ),
            )
            await self.effective_read.bump_read_revision("cancellation")
        return dict(
            await self.db.fetchone(
                "SELECT * FROM curated_results WHERE id = ?", (result_id,)
            )
        )

    async def validate_result(self, result_id: str) -> dict:
        async with self.db.transaction():
            await self._ensure_mutation_allowed()
            valid = await self.effective_read.revalidate_result(result_id)
            now = _now()
            row = await self.db.fetchone(
                "SELECT * FROM curated_results WHERE id = ?", (result_id,)
            )
            if not row:
                raise ValueError("curated result not found")
            errors = (
                await self._index_errors(result_id, row["body"], row["project_id"])
                if valid
                else []
            )
            if errors:
                valid = False
                await self.db.execute(
                    "UPDATE curated_results SET status = 'stale', stale_at = ?, stale_reason = 'curated index validation failed', revision = revision + 1 WHERE id = ? AND status = 'active'",
                    (now, result_id),
                )
                await self.effective_read.bump_read_revision("index-invalidation")
            await self.db.execute(
                "INSERT INTO reconciler_validations(id, proposal_id, result_id, stage, status, details_json, created_at) VALUES (?, ?, ?, 'read', ?, ?, ?)",
                (
                    "rv_" + uuid4().hex,
                    row["proposal_id"],
                    result_id,
                    "passed" if valid else "failed",
                    canonical_json({"errors": errors, "error": "; ".join(errors)}),
                    now,
                ),
            )
            row = await self.db.fetchone(
                "SELECT status, revision FROM curated_results WHERE id = ?",
                (result_id,),
            )
        return {
            "result_id": result_id,
            "valid": valid,
            "status": row["status"],
            "revision": int(row["revision"]),
            "errors": errors,
        }
