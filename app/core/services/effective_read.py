"""Effective read composition for canonical and active curated documents."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ..database.base import Database, anchored_path_filter_clause, value_filter_clause
from ..schemas.responses import RelatedMemory, SearchResponse, SearchResult
from .cache_manager import get_cache_manager

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _json_object(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return None


def _parse_tags(row: Any) -> Optional[List[str]]:
    try:
        value = row.get("tags") if isinstance(row, dict) else row["tags"]
    except (KeyError, IndexError):
        return None
    parsed = _json_object(value)
    return parsed if isinstance(parsed, list) and parsed else None


def _parse_anchors(row: Any) -> Optional[dict]:
    try:
        value = row.get("anchors") if isinstance(row, dict) else row["anchors"]
    except (KeyError, IndexError):
        return None
    parsed = _json_object(value)
    return parsed if isinstance(parsed, dict) and parsed else None


def _parse_starred(row: Any) -> bool:
    try:
        value = row.get("is_starred", 0) if isinstance(row, dict) else row["is_starred"]
        if isinstance(value, str):
            try:
                return bool(json.loads(value))
            except (TypeError, ValueError, json.JSONDecodeError):
                return value.strip().lower() in {"1", "true", "yes"}
        return bool(value)
    except (KeyError, IndexError):
        return False


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


class EffectiveReadService:
    """Compose effective reads without copying or changing canonical memories."""

    def __init__(self, db: Database, embedding_service: Any = None):
        self.db = db
        self.embedding_service = embedding_service
        self.cache_manager = get_cache_manager()
        self.cache_namespace = str(id(db))

    async def get_read_revision(self) -> int:
        try:
            row = await self.db.fetchone(
                "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
            )
        except Exception:
            return 0
        try:
            return int(row["state_value"]) if row else 0
        except (TypeError, ValueError):
            return 0

    async def bump_read_revision(self, reason: str = "change") -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.transaction():
            row = await self.db.fetchone(
                "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
            )
            try:
                revision = int(row["state_value"]) if row else 0
            except (TypeError, ValueError):
                revision = 0
            revision += 1
            await self.db.execute(
                "DELETE FROM reconciler_state WHERE state_key = 'read_revision'"
            )
            await self.db.execute(
                "INSERT INTO reconciler_state(state_key, state_value, updated_at) VALUES ('read_revision', ?, ?)",
                (str(revision), now),
            )
            await self.db.execute(
                "DELETE FROM reconciler_state WHERE state_key = ?",
                (f"read_revision_reason:{revision}",),
            )
            await self.db.execute(
                "INSERT INTO reconciler_state(state_key, state_value, updated_at) VALUES (?, ?, ?)",
                (f"read_revision_reason:{revision}", reason[:200], now),
            )
        return revision

    async def _active_results(self, project_id: Any = None) -> List[dict]:
        query = """
            SELECT cr.*, m.content AS representative_content, m.category AS representative_category,
                   m.source AS representative_source, m.client AS representative_client,
                   m.tags AS representative_tags, m.anchors AS representative_anchors,
                   m.is_starred AS representative_starred, m.created_at AS representative_created_at
            FROM curated_results cr
            JOIN reconciler_proposals rp ON rp.id = cr.proposal_id AND rp.status = 'applied'
            LEFT JOIN memories m ON m.id = cr.representative_memory_id
            WHERE cr.status = 'active'
        """
        params: List[Any] = []
        if project_id:
            condition, values = value_filter_clause(project_id, "cr.project_id")
            query += f" AND {condition}"
            params.extend(values)
        rows = await self.db.fetchall(query, tuple(params))
        return [dict(row) for row in rows]

    async def _source_rows(self, result_id: str) -> List[dict]:
        rows = await self.db.fetchall(
            """
            SELECT cs.memory_id, cs.input_hash, m.*
            FROM curated_sources cs
            LEFT JOIN memories m ON m.id = cs.memory_id
            WHERE cs.result_id = ? ORDER BY cs.memory_id
            """,
            (result_id,),
        )
        return [dict(row) for row in rows]

    @staticmethod
    def _scope_ids(filters: Dict[str, Any]) -> Optional[Set[str]]:
        value = filters.get("project_id")
        if not value:
            return None
        if isinstance(value, (list, tuple, set)):
            return {str(item) for item in value if item}
        return {str(value)}

    @staticmethod
    def _tag_matches(raw: Any, tag: str) -> bool:
        value = _json_object(raw)
        return isinstance(value, list) and tag in value

    @staticmethod
    def _anchor_matches(raw: Any, path: str) -> bool:
        value = _json_object(raw)
        if not isinstance(value, dict):
            return False
        paths = value.get("file_paths")
        if not isinstance(paths, list):
            return False
        normalized = str(path).replace("\\", "/").strip().rstrip("/")
        return any(
            str(item).replace("\\", "/") == normalized
            or str(item).replace("\\", "/").startswith(normalized + "/")
            for item in paths
        )

    def _source_matches(self, row: dict, filters: Dict[str, Any]) -> bool:
        if not row.get("id"):
            return False
        scopes = self._scope_ids(filters)
        if scopes is not None and row.get("project_id") not in scopes:
            return False
        categories = filters.get("category")
        if categories:
            values = (
                categories
                if isinstance(categories, (list, tuple, set))
                else [categories]
            )
            if row.get("category") not in values:
                return False
        if filters.get("source") and row.get("source") != filters["source"]:
            return False
        if filters.get("tag") and not self._tag_matches(
            row.get("tags"), filters["tag"]
        ):
            return False
        if filters.get("anchored_path") and not self._anchor_matches(
            row.get("anchors"), filters["anchored_path"]
        ):
            return False
        if filters.get("starred_only") and not bool(row.get("is_starred")):
            return False
        if row.get("status", "canonical") != "canonical":
            return False
        return True

    async def _eligible_result(self, result: dict, filters: Dict[str, Any]) -> bool:
        if not await self.revalidate_result(str(result["id"]), bump_revision=False):
            return False
        sources = await self._source_rows(result["id"])
        if not sources:
            return False
        if any(not self._source_matches(source, filters) for source in sources):
            return False
        projects = {source.get("project_id") for source in sources}
        return len(projects) == 1 and result.get("project_id") in projects

    async def raw_exclusion(self, filters: Optional[Dict[str, Any]] = None) -> Set[str]:
        """Return valid covered canonical IDs before raw ranking occurs."""

        filters = filters or {}
        excluded: Set[str] = set()
        for result in await self._active_results():
            if result.get("action") in {"add_relation", "mark_stale"}:
                continue
            if await self._eligible_result(result, filters):
                sources = await self._source_rows(result["id"])
                excluded.update(str(source["memory_id"]) for source in sources)
        return excluded

    async def _revalidate_active_results(self, project_id: Any = None) -> None:
        for result in await self._active_results(project_id):
            await self.revalidate_result(str(result["id"]))

    @staticmethod
    def _score(query: str, body: str) -> float:
        if not query.strip():
            return 0.5
        query_lower = query.casefold()
        body_lower = (body or "").casefold()
        if query_lower in body_lower:
            return min(1.0, 0.75 + len(query_lower) / max(len(body_lower), 1) * 0.25)
        words = set(_TOKEN_RE.findall(query_lower))
        if not words:
            return 0.0
        matches = sum(1 for word in words if word in body_lower)
        return matches / len(words)

    async def _curated_vector_scores(
        self, results: Sequence[dict], query_embedding: Any
    ) -> Dict[str, float]:
        if query_embedding is None or await self.db.migration_in_progress():
            return {}
        try:
            if isinstance(query_embedding, memoryview):
                query_embedding = query_embedding.tobytes()
            if isinstance(query_embedding, (bytes, bytearray)):
                import numpy as np

                query_values = np.frombuffer(query_embedding, dtype=np.float32).tolist()
            else:
                query_values = [float(item) for item in query_embedding]
        except (TypeError, ValueError):
            return {}
        if not query_values:
            return {}
        model_name = str(getattr(self.embedding_service, "model_name", "") or "")
        stored_model = await self.db.get_embedding_metadata(
            "reconciler_embedding_model"
        )
        stored_dimension = await self.db.get_embedding_metadata(
            "reconciler_embedding_dimension"
        )
        try:
            if not model_name or stored_model != model_name:
                return {}
            if not stored_dimension or int(stored_dimension) != len(query_values):
                return {}
        except (TypeError, ValueError):
            return {}
        table = "curated_results_vec_active"
        try:
            table_row = await self.db.fetchone(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            )
            table_sql = str(table_row["sql"] or "") if table_row else ""
            match = re.search(r"FLOAT\s*\[\s*(\d+)\s*\]", table_sql, re.I)
            if "USING VEC0" not in table_sql.upper() or not match:
                return {}
            if int(match.group(1)) != len(query_values):
                return {}
            expected_ids = {str(result["id"]) for result in results}
            if not expected_ids:
                return {}
            ordered_ids = sorted(expected_ids)
            placeholders = ",".join("?" for _ in ordered_ids)
            index_rows = await self.db.fetchall(
                f"SELECT result_id, embedding FROM {table} WHERE result_id IN ({placeholders})",
                tuple(ordered_ids),
            )
            actual_ids = [str(row["result_id"]) for row in index_rows]
            if (
                len(actual_ids) != len(set(actual_ids))
                or set(actual_ids) != expected_ids
            ):
                return {}
            for row in index_rows:
                value = row["embedding"]
                if isinstance(value, memoryview):
                    value = value.tobytes()
                if (
                    isinstance(value, (bytes, bytearray))
                    and len(value) != len(query_values) * 4
                ):
                    return {}
                if isinstance(value, str):
                    try:
                        if len(json.loads(value)) != len(query_values):
                            return {}
                    except (TypeError, ValueError, json.JSONDecodeError):
                        return {}
            rows = await self.db.fetchall(
                f"SELECT result_id, distance FROM {table} WHERE embedding MATCH ? AND result_id IN (SELECT value FROM json_each(?)) AND k = ? ORDER BY distance",
                (json.dumps(query_values), json.dumps(ordered_ids), len(expected_ids)),
            )
            return {
                str(row["result_id"]): max(0.0, 1.0 - float(row["distance"]))
                for row in rows
                if row["distance"] is not None
            }
        except Exception as exc:
            logger.debug("Curated vector scoring unavailable: %s", exc)
            return {}

    @staticmethod
    def _curated_result(
        result: dict, sources: Sequence[dict], score: float
    ) -> SearchResult:
        citations = [
            {
                "memory_id": str(row["memory_id"]),
                "input_hash": str(row["input_hash"]),
                "source_role": (
                    "representative"
                    if row["memory_id"] == result.get("representative_memory_id")
                    else "source"
                ),
            }
            for row in sources
        ]
        tags = (
            _parse_tags(result)
            if "tags" in result
            else _parse_tags({"tags": result.get("representative_tags")})
        )
        return SearchResult(
            id=str(result["id"]),
            content=str(result.get("body") or ""),
            similarity_score=float(score),
            created_at=str(
                result.get("created_at")
                or result.get("representative_created_at")
                or ""
            ),
            project_id=result.get("project_id"),
            category=str(result.get("representative_category") or "task"),
            source="reconciler",
            client=result.get("representative_client"),
            tags=tags,
            anchors=_parse_anchors(
                {"anchors": result.get("representative_anchors")}
                if "representative_anchors" in result
                else result
            ),
            is_starred=bool(result.get("representative_starred")),
            result_kind="curated",
            representative_memory_id=result.get("representative_memory_id"),
            citations=citations,
        )

    async def search_curated(
        self,
        query: str,
        query_embedding: Any = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 20,
    ) -> List[SearchResult]:
        """Search derived FTS/vector rows independently from canonical rows."""

        filters = filters or {}
        if (
            query_embedding is None
            and query.strip()
            and self.embedding_service is not None
        ):
            try:
                query_embedding = await self.embedding_service.aembed(query)
            except Exception as exc:
                logger.debug("Curated query embedding failed: %s", exc)
                query_embedding = None
        results: List[SearchResult] = []
        active_results = await self._active_results(filters.get("project_id"))
        vector_results = await self._active_results()
        vector_scores = await self._curated_vector_scores(
            vector_results, query_embedding
        )
        fts_scores: Dict[str, float] = {}
        if query.strip():
            try:
                fts_rows = await self.db.fetchall(
                    "SELECT result_id FROM curated_results_fts WHERE curated_results_fts MATCH ?",
                    (query,),
                )
                fts_scores = {str(row["result_id"]): 0.5 for row in fts_rows}
            except Exception as exc:
                logger.debug("Curated FTS scoring unavailable: %s", exc)
        for result in active_results:
            if not await self._eligible_result(result, filters):
                continue
            if result.get("action") in {
                "archive",
                "quarantine",
                "noise_suppression",
                "add_relation",
                "mark_stale",
            }:
                continue
            sources = await self._source_rows(result["id"])
            lexical_score = self._score(query, str(result.get("body") or ""))
            text_score = max(lexical_score, fts_scores.get(str(result["id"]), 0.0))
            score = max(text_score, vector_scores.get(str(result["id"]), 0.0))
            if query.strip() and score <= 0:
                continue
            results.append(self._curated_result(result, sources, score))
        results.sort(key=lambda item: (-item.similarity_score, item.id))
        return results[: max(0, limit)]

    async def _raw_candidates(
        self, query: str, filters: Dict[str, Any], limit: int, offset: int = 0
    ) -> List[SearchResult]:
        excluded = await self.raw_exclusion(filters)
        conditions = ["COALESCE(m.status, 'canonical') = 'canonical'"]
        params: List[Any] = []
        condition, values = value_filter_clause(
            filters.get("project_id"), "m.project_id"
        )
        if condition:
            conditions.append(condition)
            params.extend(values)
        if filters.get("category"):
            condition, values = value_filter_clause(filters["category"], "m.category")
            conditions.append(condition)
            params.extend(values)
        if filters.get("source"):
            conditions.append("m.source = ?")
            params.append(filters["source"])
        if filters.get("tag"):
            conditions.append(
                "json_valid(m.tags) AND EXISTS (SELECT 1 FROM json_each(m.tags) WHERE json_each.value = ?)"
            )
            params.append(filters["tag"])
        if filters.get("anchored_path"):
            condition, values = anchored_path_filter_clause(
                filters["anchored_path"], "m.anchors"
            )
            if condition:
                conditions.append(condition)
                params.extend(values)
        if filters.get("starred_only"):
            conditions.append("m.is_starred = 1")
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            conditions.append(f"m.id NOT IN ({placeholders})")
            params.extend(sorted(excluded))
        rows = await self.db.fetchall(
            "SELECT m.* FROM memories m WHERE "
            + " AND ".join(conditions)
            + " ORDER BY m.created_at DESC",
            tuple(params),
        )
        results = []
        for row in rows:
            item = SearchResult(
                id=str(row["id"]),
                content=str(row["content"] or ""),
                similarity_score=self._score(query, str(row["content"] or "")),
                created_at=str(row["created_at"] or ""),
                project_id=row["project_id"],
                category=str(row["category"] or "task"),
                source=str(row["source"] or ""),
                client=row["client"] if "client" in row.keys() else None,
                tags=_parse_tags(row),
                anchors=_parse_anchors(row),
                is_starred=_parse_starred(row),
            )
            if query.strip() and item.similarity_score <= 0:
                continue
            results.append(item)
        results.sort(
            key=lambda item: (-item.similarity_score, item.created_at, item.id)
        )
        return results[offset : offset + limit]

    async def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 5,
        offset: int = 0,
        query_embedding: Any = None,
    ) -> SearchResponse:
        """Search derived and uncovered canonical rows before applying top-k."""

        filters = filters or {}
        await self._revalidate_active_results(filters.get("project_id"))
        revision = await self.get_read_revision()
        cache_category = filters.get("category")
        if isinstance(cache_category, (list, tuple, set)):
            cache_category = ",".join(sorted(str(item) for item in cache_category))
        cache_compatible = (
            bool(query.strip()) and not await self.db.migration_in_progress()
        )
        if self.embedding_service is not None:
            configured_model = str(
                getattr(self.embedding_service, "model_name", "") or ""
            )
            configured_dimension = getattr(self.embedding_service, "dimension", None)
            stored_model = await self.db.get_embedding_metadata(
                "reconciler_embedding_model"
            )
            stored_dimension = await self.db.get_embedding_metadata(
                "reconciler_embedding_dimension"
            )
            try:
                cache_compatible = cache_compatible and bool(
                    configured_model
                    and stored_model == configured_model
                    and stored_dimension
                    and int(stored_dimension) == int(configured_dimension)
                )
            except (TypeError, ValueError):
                cache_compatible = False
        cached = None
        if cache_compatible:
            cached = await self.cache_manager.get_cached_search(
                query=query,
                project_id=self.cache_namespace
                + ":"
                + str(filters.get("project_id") or ""),
                category=cache_category,
                limit=limit,
                read_view="effective",
                read_revision=revision,
            )
        if cached is not None and offset == 0:
            return cached
        curated = await self.search_curated(
            query, query_embedding, filters, limit=max(limit * 4, 20)
        )
        raw = await self._raw_candidates(query, filters, limit=max(limit * 4, 20))
        response = self.compose_search(raw, curated, limit=limit, offset=offset)
        if cache_compatible and offset == 0:
            await self.cache_manager.cache_search_results(
                query=query,
                results=response,
                project_id=self.cache_namespace
                + ":"
                + str(filters.get("project_id") or ""),
                category=cache_category,
                limit=limit,
                read_view="effective",
                read_revision=revision,
            )
        return response

    def compose_search(
        self,
        raw_candidates: Iterable[SearchResult],
        curated_candidates: Iterable[SearchResult],
        limit: int,
        offset: int = 0,
    ) -> SearchResponse:
        merged: Dict[str, SearchResult] = {}
        for item in list(raw_candidates) + list(curated_candidates):
            current = merged.get(item.id)
            if current is None or item.similarity_score > current.similarity_score:
                merged[item.id] = item
        values = sorted(
            merged.values(), key=lambda item: (-item.similarity_score, item.id)
        )
        page = values[offset : offset + limit]
        return SearchResponse(results=page, total=len(values))

    async def resolve_primary(
        self,
        result_id: str,
        read_view: str = "effective",
        filters: Optional[Dict[str, Any]] = None,
    ) -> Optional[SearchResult]:
        """Resolve canonical IDs raw and curated IDs only as derived documents."""

        filters = filters or {}
        if str(result_id).startswith("cr_"):
            row = await self.db.fetchone(
                "SELECT cr.*, m.tags AS representative_tags, m.anchors AS representative_anchors, m.category AS representative_category, m.source AS representative_source, m.client AS representative_client, m.is_starred AS representative_starred, m.created_at AS representative_created_at FROM curated_results cr LEFT JOIN memories m ON m.id = cr.representative_memory_id WHERE cr.id = ? AND cr.status = 'active'",
                (result_id,),
            )
            if not row:
                return None
            result = dict(row)
            if not await self._eligible_result(result, filters):
                return None
            if result.get("action") in {"archive", "quarantine", "noise_suppression"}:
                return None
            return self._curated_result(result, await self._source_rows(result_id), 1.0)
        if read_view == "effective":
            for result in await self._active_results(filters.get("project_id")):
                if not await self._eligible_result(result, filters):
                    continue
                if any(
                    row["memory_id"] == result_id
                    for row in await self._source_rows(result["id"])
                ):
                    if result.get("action") in {
                        "archive",
                        "quarantine",
                        "noise_suppression",
                    }:
                        return None
                    return self._curated_result(
                        result, await self._source_rows(result["id"]), 1.0
                    )
        row = await self.db.fetchone(
            "SELECT * FROM memories WHERE id = ?", (result_id,)
        )
        if not row:
            return None
        scopes = self._scope_ids(filters)
        if scopes is not None and row["project_id"] not in scopes:
            return None
        return SearchResult(
            id=str(row["id"]),
            content=str(row["content"] or ""),
            similarity_score=1.0,
            created_at=str(row["created_at"] or ""),
            project_id=row["project_id"],
            category=str(row["category"] or "task"),
            source=str(row["source"] or ""),
            client=row["client"] if "client" in row.keys() else None,
            tags=_parse_tags(row),
            anchors=_parse_anchors(row),
            is_starred=_parse_starred(row),
        )

    async def related(
        self,
        result: SearchResult,
        depth: int = 2,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RelatedMemory]:
        """Return related effective results from the primary result's project."""

        limit = max(0, depth) * 3
        if not limit:
            return []
        scoped_filters = {**(filters or {}), "project_id": result.project_id}
        if result.result_kind == "curated" and not scoped_filters.get("anchored_path"):
            source_rows = await self._source_rows(result.id)
            anchor_sets = [
                set((_parse_anchors(row) or {}).get("file_paths") or [])
                for row in source_rows
            ]
            if anchor_sets and all(anchor_sets):
                common_anchors = set.intersection(*anchor_sets)
                if common_anchors:
                    scoped_filters["anchored_path"] = sorted(
                        common_anchors, key=lambda value: (-len(value), value)
                    )[0]
        response = await self.search(
            result.content[:500], scoped_filters, limit=limit + 1
        )
        return [
            RelatedMemory(
                id=item.id,
                content=item.content,
                similarity_score=item.similarity_score,
                relationship="similar",
                created_at=item.created_at,
                category=item.category,
                project_id=item.project_id,
                result_kind=item.result_kind,
                representative_memory_id=item.representative_memory_id,
                citations=item.citations,
            )
            for item in response.results
            if item.id != result.id
        ][:limit]

    async def revalidate_result(
        self, result_id: str, bump_revision: bool = True
    ) -> bool:
        """Exclude a result immediately when any canonical input fingerprint changes."""

        row = await self.db.fetchone(
            "SELECT cr.id, cr.project_id, cr.status, cr.representative_memory_id, c.memory_ids_json "
            "FROM curated_results cr LEFT JOIN reconciler_candidates c ON c.id = cr.candidate_id WHERE cr.id = ?",
            (result_id,),
        )
        if not row or row["status"] != "active":
            return False
        sources = await self._source_rows(result_id)
        expected_ids = _json_object(row["memory_ids_json"])
        source_ids = {source["memory_id"] for source in sources}
        stale = (
            not isinstance(expected_ids, list)
            or not sources
            or source_ids != set(expected_ids)
            or row["representative_memory_id"] not in source_ids
            or any(source.get("project_id") != row["project_id"] for source in sources)
        )
        reason = (
            "curated source provenance changed"
            if stale
            else "canonical input hash changed"
        )
        for source in sources:
            current = await self.current_input_hash(source["memory_id"])
            if current is None or current != source["input_hash"]:
                stale = True
                break
        if not stale:
            return True
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.transaction():
            changed = await self.db.execute(
                "UPDATE curated_results SET status = 'stale', stale_at = ?, stale_reason = ?, revision = revision + 1 WHERE id = ? AND status = 'active'",
                (now, reason, result_id),
            )
            await self.db.execute(
                "UPDATE reconciler_state SET state_value = ?, updated_at = ? WHERE state_key = ?",
                ("stale", now, f"overview_stale:{row['project_id']}"),
            )
        if bump_revision and changed.rowcount == 1:
            await self.bump_read_revision("input-invalidation")
        return False

    async def current_input_hash(self, memory_id: str) -> Optional[str]:
        row = await self.db.fetchone(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        )
        if not row:
            return None
        relation_rows = await self.db.fetchall(
            "SELECT source_id, target_id, relation_type, strength, metadata FROM memory_relations WHERE source_id = ? OR target_id = ? ORDER BY source_id, target_id, relation_type, id",
            (memory_id, memory_id),
        )
        payload = {
            "memory_id": row["id"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "project_id": row["project_id"],
            "category": row["category"],
            "source": row["source"],
            "client": row["client"] if "client" in row.keys() else None,
            "tags": row["tags"],
            "status": row["status"] if "status" in row.keys() else "canonical",
            "anchors": row["anchors"] if "anchors" in row.keys() else None,
            "is_starred": row["is_starred"] if "is_starred" in row.keys() else 0,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "relations": [dict(item) for item in relation_rows],
        }
        if "stale_status" in row.keys() and row["stale_status"] is not None:
            payload["stale_status"] = row["stale_status"]
        if "reconciler_protected" in row.keys() and row["reconciler_protected"]:
            payload["reconciler_protected"] = True
        return _stable_hash(payload)
