"""Federated hub search — a thin layer ABOVE the local search pipeline.

Clients (MCP / dashboard) only ever talk to their personal mem-mesh node; this
service is how that node reaches the team hub server-side. On ``scope="all"``
it runs the local search and a hub query in parallel and fuses them with
weighted RRF (local outranks hub at equal rank). The hub being slow or down
NEVER fails the search — it degrades to local results with a ``hub_status``
flag on the response.

Deliberately NOT wired into UnifiedSearchService: the core pipeline (cache,
noise filter, rerank) stays local-only and free of relay/httpx imports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from ..schemas.relay import RelaySearchRequest, RelaySearchResult
from ..schemas.responses import SearchResponse, SearchResult
from .relay import RelayHTTPClient, RelayService
from .relay_fusion import fuse_relay_results_rrf

logger = logging.getLogger(__name__)

# hub_status values surfaced on SearchResponse
HUB_OK = "ok"
HUB_UNAVAILABLE = "unavailable"
HUB_SKIPPED = "skipped"

_FUSION_INTERNAL_KEYS = ("sources", "rrf_score")

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


class FederatedHubSearch:
    """Fuse local search results with the team hub's relay search."""

    def __init__(
        self,
        db: Any,
        settings: Any,
        http_client: Optional[RelayHTTPClient] = None,
    ):
        self.db = db
        self.settings = settings
        self.http_client = http_client or RelayHTTPClient(
            http_client=_get_shared_httpx_client(),
            timeout=getattr(settings, "relay_federated_timeout", 2.5),
        )
        self._relay_service: Optional[RelayService] = None

    def _relay(self) -> RelayService:
        if self._relay_service is None:
            self._relay_service = RelayService(self.db)
        return self._relay_service

    async def _hub_config(self) -> dict[str, str]:
        config = await self._relay().get_effective_config(self.settings)
        values = config.get("values", {})
        return {
            "hub_url": str(values.get("hub_url") or "").strip(),
            "hub_token": str(values.get("hub_token") or "").strip(),
            "source_node_id": str(values.get("source_node_id") or "").strip(),
        }

    async def fetch_hub_results(
        self, *, query: str, limit: int, categories: Optional[list[str]] = None
    ) -> tuple[list[SearchResult], str]:
        """Query the hub; never raises. Returns (results, hub_status).

        ``categories`` filters hub results client-side by ``kind`` so a
        category-scoped search doesn't get unrelated hub kinds mixed in (the
        hub search endpoint has no kind filter yet).
        """
        try:
            cfg = await self._hub_config()
        except Exception as exc:
            logger.warning("Federated search: relay config lookup failed: %s", exc)
            return [], HUB_SKIPPED
        if not cfg["hub_url"] or not cfg["hub_token"]:
            return [], HUB_SKIPPED

        payload = RelaySearchRequest(
            query=query,
            limit=max(1, min(limit, 50)),
            exclude_source_node=cfg["source_node_id"] or None,
        )
        timeout = getattr(self.settings, "relay_federated_timeout", 2.5)
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
            logger.warning("Federated search: hub unavailable: %s", exc)
            return [], HUB_UNAVAILABLE

        results = []
        category_set = {c for c in (categories or []) if c}
        for item in response.results:
            # Belt-and-braces: an older hub ignores exclude_source_node, so we
            # also drop our own node's items client-side.
            if cfg["source_node_id"] and item.source_node_id == cfg["source_node_id"]:
                continue
            # Respect the caller's category filter (hub kind == memory category).
            if category_set and item.kind not in category_set:
                continue
            results.append(self._to_search_result(item))
        return results, HUB_OK

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

        hub_weight = getattr(self.settings, "relay_federated_hub_weight", 0.75)
        fused = fuse_relay_results_rrf(
            [r.model_dump() for r in local_response.results],
            [r.model_dump() for r in hub_results],
            limit=limit,
            weights={"local": 1.0, "hub": hub_weight},
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
