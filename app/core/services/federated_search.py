"""Federated hub search — a thin layer ABOVE the local search pipeline.

Clients (MCP / dashboard) only ever talk to their personal mem-mesh node; this
service is how that node reaches the team hub server-side. On ``scope="all"``
it runs the local search and a hub query in parallel and fuses them on raw
similarity — both corpora are scored by the same embedding model, so their
scores are directly comparable. The hub being slow or down NEVER fails the
search — it degrades to local results with a ``hub_status`` flag on the
response.

Deliberately NOT wired into UnifiedSearchService: the core pipeline (cache,
noise filter, rerank) stays local-only and free of relay/httpx imports.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from ..schemas.relay import RelaySearchRequest, RelaySearchResult
from ..schemas.responses import SearchResponse, SearchResult
from .relay import RelayHTTPClient, RelayService
from .relay_fusion import fuse_relay_results_by_score

logger = logging.getLogger(__name__)

# hub_status values surfaced on SearchResponse
HUB_OK = "ok"
HUB_UNAVAILABLE = "unavailable"
HUB_SKIPPED = "skipped"

_FUSION_INTERNAL_KEYS = ("sources", "rrf_score", "fusion_score")

# Shipped default of relay_federated_hub_weight. Only a value the operator
# actually changed is worth warning about.
_DEFAULT_HUB_WEIGHT = 0.75

# Process-wide latch so the deprecation warning fires once, not per search.
_hub_weight_warned = False

# Shared connection pool for hub calls. FederatedHubSearch instances are built
# per-request, so a per-instance client would open a fresh TCP+TLS connection
# on every federated search (flagged in cross-vendor review). Lazily created,
# lives for the process — standard httpx long-lived-client usage.
_shared_httpx_client: Any = None


def _get_shared_httpx_client() -> Any:
    global _shared_httpx_client
    if _shared_httpx_client is None:
        import httpx

        _shared_httpx_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
        )
    return _shared_httpx_client


class HubCircuitBreaker:
    """Per-hub failure memory so a down hub stops costing the full timeout.

    FederatedHubSearch instances are per-request; without cross-request state,
    every scope=all/hub search against a dead hub blocks for
    relay_federated_timeout (~2.5s). This breaker opens after ``threshold``
    consecutive failures and short-circuits hub calls for ``cooldown`` seconds;
    after the cooldown one probe request is let through (half-open) and a
    success closes the breaker again.

    In-process only (personal nodes are single-process); keyed by hub URL so a
    hub_url change gets a fresh state. ``clock`` is injectable for tests.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        # hub_url -> [consecutive_failures, open_until_monotonic]
        self._state: dict[str, list[float]] = {}

    def allow(self, hub_url: str, *, threshold: int, cooldown: float) -> bool:
        state = self._state.get(hub_url)
        if state is None or state[0] < threshold:
            return True
        now = self._clock()
        if now >= state[1]:
            # Half-open: let one probe through; a failure re-opens (record_failure
            # pushes open_until forward), a success resets entirely.
            state[1] = now + cooldown
            return True
        return False

    def record_success(self, hub_url: str) -> None:
        self._state.pop(hub_url, None)

    def record_failure(self, hub_url: str, *, threshold: int, cooldown: float) -> None:
        state = self._state.setdefault(hub_url, [0, 0.0])
        state[0] += 1
        if state[0] >= threshold:
            state[1] = self._clock() + cooldown
            logger.warning(
                "Federated search: circuit open for %s after %d consecutive "
                "failures (cooldown %.1fs)",
                hub_url,
                int(state[0]),
                cooldown,
            )


# Process-wide breaker shared by all per-request FederatedHubSearch instances.
_shared_breaker = HubCircuitBreaker()


class FederatedHubSearch:
    """Fuse local search results with the team hub's relay search."""

    def __init__(
        self,
        db: Any,
        settings: Any,
        http_client: Optional[RelayHTTPClient] = None,
        breaker: Optional[HubCircuitBreaker] = None,
    ):
        self.db = db
        self.settings = settings
        self.http_client = http_client or RelayHTTPClient(
            http_client=_get_shared_httpx_client(),
            timeout=getattr(settings, "relay_federated_timeout", 2.5),
        )
        self.breaker = breaker or _shared_breaker
        self._relay_service: Optional[RelayService] = None

    def _relay(self) -> RelayService:
        if self._relay_service is None:
            self._relay_service = RelayService(self.db)
        return self._relay_service

    @staticmethod
    def _coerce_float(raw: Any, default: float) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return value

    async def _hub_config(self) -> dict[str, Any]:
        config = await self._relay().get_effective_config(self.settings)
        values = config.get("values", {})
        # DB > env > default: the effective-config values already resolve DB
        # overrides; fall back to the settings attribute when unset/unparseable.
        timeout = self._coerce_float(
            values.get("federated_timeout"),
            getattr(self.settings, "relay_federated_timeout", 2.5),
        )
        hub_weight = self._coerce_float(
            values.get("federated_hub_weight"),
            getattr(self.settings, "relay_federated_hub_weight", 0.75),
        )
        # Remember the effective hub weight so the scope=all fuse (which runs
        # after this config load) uses the DB-backed value without re-reading.
        self._hub_weight_effective = hub_weight
        return {
            "hub_url": str(values.get("hub_url") or "").strip(),
            "hub_token": str(values.get("hub_token") or "").strip(),
            "source_node_id": str(values.get("source_node_id") or "").strip(),
            "timeout": timeout,
            "hub_weight": hub_weight,
        }

    def _warn_hub_weight_ignored_once(self) -> None:
        """Tell the operator their configured hub weight no longer does anything.

        Score fusion replaced rank fusion, and a rank multiplier has no honest
        translation into score space. Silently dropping a value someone set is
        worse than the original bug was to diagnose, so say it out loud — once
        per process, since this runs on every federated search.
        """
        global _hub_weight_warned
        if _hub_weight_warned:
            return
        hub_weight = getattr(self, "_hub_weight_effective", _DEFAULT_HUB_WEIGHT)
        if hub_weight == _DEFAULT_HUB_WEIGHT:
            return
        _hub_weight_warned = True
        logger.warning(
            "relay_federated_hub_weight=%.2f is ignored: federated search now "
            "fuses on similarity score, not rank, so a rank multiplier has no "
            "effect. To bias results toward local memories, use the "
            "hub_penalty argument (a flat margin in score units) instead.",
            hub_weight,
        )

    def _breaker_params(self) -> tuple[int, float]:
        threshold = int(
            getattr(self.settings, "relay_federated_breaker_threshold", 3) or 3
        )
        cooldown = float(
            getattr(self.settings, "relay_federated_breaker_cooldown", 30.0) or 30.0
        )
        return max(1, threshold), max(1.0, cooldown)

    async def fetch_hub_results(
        self, *, query: str, limit: int, categories: Optional[list[str]] = None
    ) -> tuple[list[SearchResult], str]:
        """Query the hub; never raises. Returns (results, hub_status).

        ``categories`` is sent to the hub as a server-side ``kinds`` filter and
        re-applied client-side (an older hub ignores the field). A circuit
        breaker skips the hub call entirely while it is known-down, so degraded
        searches don't pay the full timeout on every request.
        """
        try:
            cfg = await self._hub_config()
        except Exception as exc:
            logger.warning("Federated search: relay config lookup failed: %s", exc)
            return [], HUB_SKIPPED
        if not cfg["hub_url"] or not cfg["hub_token"]:
            return [], HUB_SKIPPED

        threshold, cooldown = self._breaker_params()
        if not self.breaker.allow(
            cfg["hub_url"], threshold=threshold, cooldown=cooldown
        ):
            logger.debug(
                "Federated search: circuit open, skipping hub %s", cfg["hub_url"]
            )
            return [], HUB_UNAVAILABLE

        category_set = {c for c in (categories or []) if c}
        # Over-fetch when a category filter applies: an older hub ignores the
        # kinds field, and the client-side re-filter below would otherwise
        # silently shrink the hub's contribution under the requested limit.
        hub_limit = min(limit * 2, 50) if category_set else min(limit, 50)
        payload = RelaySearchRequest(
            query=query,
            limit=max(1, hub_limit),
            exclude_source_node=cfg["source_node_id"] or None,
            kinds=sorted(category_set) or None,
        )
        timeout = cfg.get(
            "timeout", getattr(self.settings, "relay_federated_timeout", 2.5)
        )
        try:
            response = await asyncio.wait_for(
                self.http_client.send_search(
                    target_hub=cfg["hub_url"],
                    bearer_token=cfg["hub_token"],
                    payload=payload,
                    timeout=timeout,
                ),
                timeout=timeout + 0.5,
            )
        except Exception as exc:
            # Timeout, connection error, auth failure, old-hub 4xx — all degrade.
            self.breaker.record_failure(
                cfg["hub_url"], threshold=threshold, cooldown=cooldown
            )
            logger.warning("Federated search: hub unavailable: %s", exc)
            return [], HUB_UNAVAILABLE

        self.breaker.record_success(cfg["hub_url"])
        results = []
        for item in response.results:
            # Belt-and-braces: an older hub ignores exclude_source_node, so we
            # also drop our own node's items client-side.
            if cfg["source_node_id"] and item.source_node_id == cfg["source_node_id"]:
                continue
            # Respect the caller's category filter (hub kind == memory category).
            if category_set and item.kind not in category_set:
                continue
            results.append(self._to_search_result(item))
        # The over-fetched window may survive filtering intact — honor the
        # caller's limit.
        return results[: max(1, limit)], HUB_OK

    @staticmethod
    def _to_search_result(item: RelaySearchResult) -> SearchResult:
        return SearchResult(
            id=item.id,
            content=item.content,
            similarity_score=item.score,
            created_at=item.updated_at or "",
            project_id=item.team_project_id,
            category=item.kind,
            source="relay-hub",
            tags=item.tags or None,
            origin="hub",
            title=item.title,
            abstract=item.abstract,
        )

    async def search(
        self,
        *,
        scope: str,
        query: str,
        limit: int,
        local_search: Callable[[], Awaitable[SearchResponse]],
        categories: Optional[list[str]] = None,
    ) -> SearchResponse:
        """Run a scoped search. ``local_search`` is the existing local pipeline."""
        # Unknown scope values fall back to the safe default instead of
        # silently running the federated path.
        if scope not in ("local", "hub", "all"):
            scope = "local"
        if scope == "local":
            return await local_search()

        if scope == "hub":
            hub_results, hub_status = await self.fetch_hub_results(
                query=query, limit=limit, categories=categories
            )
            return SearchResponse(
                results=hub_results,
                total=len(hub_results),
                hub_status=hub_status,
            )

        # scope == "all": run both concurrently; hub failure degrades to local.
        hub_task = asyncio.create_task(
            self.fetch_hub_results(query=query, limit=limit, categories=categories)
        )
        try:
            local_response = await local_search()
        except BaseException:
            # BaseException so CancelledError also releases the hub task.
            hub_task.cancel()
            raise
        hub_results, hub_status = await hub_task

        if not hub_results:
            local_response.hub_status = hub_status
            return local_response

        # Fuse on raw similarity, not rank. Both sides are scored by the same
        # embedding model, so the scores are directly comparable — and rank
        # fusion structurally truncated every hub result away (see
        # fuse_relay_results_by_score).
        #
        # relay_federated_hub_weight is deliberately NOT applied here: it was a
        # rank multiplier and does not survive the move to score space. Scores
        # sit in a narrow band (unrelated hits still score ~0.5), so scaling a
        # 0.561 hub hit by 0.75 yields 0.42 and loses to a 0.525 local hit that
        # matches nothing — reinstating the very bug this replaces. Preferring
        # local now belongs in hub_penalty, a flat margin in score units.
        self._warn_hub_weight_ignored_once()
        fused = fuse_relay_results_by_score(
            [r.model_dump() for r in local_response.results],
            [r.model_dump() for r in hub_results],
            limit=limit,
        )
        results = []
        for entry in fused:
            origin = (entry.get("sources") or ["local"])[0]
            data = {k: v for k, v in entry.items() if k not in _FUSION_INTERNAL_KEYS}
            data["origin"] = origin
            results.append(SearchResult(**data))

        local_response.results = results
        local_response.total = len(results)
        local_response.hub_status = hub_status
        return local_response


# --- WS2: session digest cache (worker prefetch → session-start read) ---------

# app_config key namespace shared by the relay worker (writer, t4) and the
# session-start read helper (reader, t5). One row per subscribed team project.
_SESSION_DIGEST_KEY_PREFIX = "relay.session_digest."


def session_digest_config_key(project_id: str) -> str:
    """app_config key holding the cached team hub digest for ``project_id``."""
    return f"{_SESSION_DIGEST_KEY_PREFIX}{project_id}"


def _parse_iso_utc(value: str) -> Optional[datetime]:
    """Best-effort parse of an ISO-8601 UTC timestamp (with or without 'Z')."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def read_cached_team_digest(
    db: Any, project_id: str, settings: Any = None
) -> Optional[dict]:
    """Read the cached team hub digest for a project — local read only (N1).

    Returns ``{summary, source_count, generated_at}`` when a fresh cached digest
    exists AND the project's auto-share subscription is enabled; otherwise None.
    Makes ZERO network calls and swallows every error into None (N2), so the
    session-start path can call it best-effort without ever failing a session.
    """
    try:
        if settings is None:
            from ..config import get_settings

            settings = get_settings()
        if not getattr(settings, "relay_federated_session_digest_enabled", True):
            return None

        # Gate on the auto-share subscription: only surface team context the user
        # opted this project into (RelayService.get_project_auto_share precedent).
        sub = await RelayService(db).get_project_auto_share(project_id)
        if sub is None or not getattr(sub, "enabled", False):
            return None

        raw = await db.get_app_config(session_digest_config_key(project_id))
        if not raw:
            return None
        payload = json.loads(raw)

        fetched_at = _parse_iso_utc(payload.get("fetched_at", ""))
        if fetched_at is None:
            return None
        max_age_minutes = getattr(
            settings, "relay_federated_session_digest_max_age_minutes", 60
        )
        age_seconds = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age_seconds > max_age_minutes * 60:
            return None

        summary = payload.get("summary")
        if not summary:
            return None
        return {
            "summary": summary,
            "source_count": payload.get("source_count", 0),
            "generated_at": payload.get("generated_at"),
        }
    except Exception as exc:  # noqa: BLE001 — session-start read must never raise
        logger.debug("read_cached_team_digest skipped", extra={"error": str(exc)})
        return None
