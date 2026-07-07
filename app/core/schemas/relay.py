"""Schemas for the mem-mesh relay layer."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

RelayEventType = Literal["create", "update", "retract"]
# Was a Literal of 7 known categories — that made this a 4th hardcoded
# category enum (alongside the old sharing gate, the dashboard's edit
# dropdown, and CLAUDE.md's documented list), so a newly introduced category
# would fail wire validation even after the sharing gate allowed it. The
# actual policy (denylist + user opt-out) lives in RelayService; this is just
# a bounded free-form label matching Memory.category's own type.
RelayKind = str


class RelayIngestRequest(BaseModel):
    """S2S relay ingest payload sent from a personal node to the team hub."""

    idempotency_key: str = Field(min_length=1, max_length=300)
    payload_hash: str = Field(min_length=1, max_length=128)
    event_type: RelayEventType
    source_memory_id: str = Field(min_length=1, max_length=200)
    source_version: int = Field(ge=0)
    source_project_key: str = Field(min_length=1, max_length=200)
    kind: RelayKind = Field(min_length=1, max_length=100)
    status: str = Field(default="active", min_length=1, max_length=50)
    content: Optional[str] = Field(default=None, max_length=50000)
    tags: List[str] = Field(default_factory=list)
    links: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Optional pre-baked enrichment (from the sender's local "Enrich" button,
    # app.core.services.enrich_store.EnrichmentStore) carried along so the hub
    # doesn't need its own relay item-worker/LLM to show a title/abstract.
    title: Optional[str] = Field(default=None, max_length=500)
    abstract: Optional[str] = Field(default=None, max_length=4000)
    display_kind: Optional[str] = Field(default=None, max_length=100)

    @field_validator("tags", "links")
    @classmethod
    def _limit_string_lists(cls, value: List[str]) -> List[str]:
        if len(value) > 100:
            raise ValueError("relay list fields may contain at most 100 items")
        return [item for item in value if item]

    @model_validator(mode="after")
    def _content_required_for_visible_events(self) -> "RelayIngestRequest":
        if self.event_type in {"create", "update"} and not self.content:
            raise ValueError("content is required for create/update relay events")
        return self


class RelayIngestResponse(BaseModel):
    """Result of deterministic relay ingest."""

    accepted: bool
    event_id: str
    current_memory_id: Optional[str]
    current_created: bool = False
    replayed: bool = False
    applied_to_current: bool = False
    queued_item: bool = False


class RelayQueueJob(BaseModel):
    """Claimed SQLite queue job."""

    id: str
    ref_id: str
    raw_event_id: str
    status: str
    attempts: int
    locked_by: Optional[str] = None
    locked_at: Optional[float] = None


class RelayAggregateJob(BaseModel):
    """Claimed aggregate digest queue job."""

    id: str
    ref_id: str
    raw_event_id: Optional[str] = None
    coalesce_key: str
    status: str
    attempts: int
    locked_by: Optional[str] = None
    locked_at: Optional[float] = None


class RelayOutboxJob(BaseModel):
    """Claimed personal-node relay outbox job."""

    id: str
    idempotency_key: str
    payload_hash: str
    payload: RelayIngestRequest
    target_hub: str
    status: str
    attempts: int
    locked_by: Optional[str] = None
    locked_at: Optional[float] = None


class RelayProcessResult(BaseModel):
    """Result of one worker processing attempt."""

    processed: bool
    job_id: Optional[str] = None
    current_memory_id: Optional[str] = None
    error: Optional[str] = None


class RelayEnrichmentData(BaseModel):
    """Structured output produced by a relay text enricher."""

    title: str = ""
    abstract: str = ""
    tags: List[str] = Field(default_factory=list)
    display_kind: str = ""
    problem: Optional[str] = None
    resolution: Optional[str] = None
    lesson: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @classmethod
    def from_result(cls, value: Any) -> "RelayEnrichmentData":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(**value)
        if hasattr(value, "model_dump"):
            return cls(**value.model_dump())
        raise TypeError("text enricher must return dict or RelayEnrichmentData")


class RelayDigestData(BaseModel):
    """Structured project digest output."""

    rollup: Dict[str, Any] = Field(default_factory=dict)
    contributors: List[str] = Field(default_factory=list)
    recent_activity: List[Any] = Field(default_factory=list)
    narrative: str = ""
    source_memory_ids: List[str] = Field(default_factory=list)

    @classmethod
    def from_result(cls, value: Any) -> "RelayDigestData":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(**value)
        if hasattr(value, "model_dump"):
            return cls(**value.model_dump())
        raise TypeError("digest generator must return dict or RelayDigestData")


class RelaySearchResult(BaseModel):
    """Simple hub-view search result for the relay MVP."""

    id: str
    content: str
    team_project_id: str
    source_node_id: str
    source_memory_id: str
    source_version: int
    kind: str
    status: str
    tags: List[str] = Field(default_factory=list)
    title: Optional[str] = None
    abstract: Optional[str] = None
    rank: int
    score: float
    updated_at: Optional[str] = None


class RelaySearchRequest(BaseModel):
    """Hub-view relay search request."""

    query: str = ""
    team_project_ids: Optional[List[str]] = None
    limit: int = Field(default=10, ge=1, le=50)
    # Federated search: a personal node passes its own source_node_id so the hub
    # omits memories that node itself pushed (they already rank in local results).
    # Older hubs ignore this field; callers must also filter client-side.
    exclude_source_node: Optional[str] = Field(default=None, max_length=200)
    # Category filter applied hub-side (kind == memory category). Older hubs
    # ignore this field; callers must also filter client-side.
    kinds: Optional[List[str]] = Field(default=None, max_length=20)


class RelaySearchResponse(BaseModel):
    results: List[RelaySearchResult]
    total: int
    team_results_unavailable: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RelayProjectDigestResponse(BaseModel):
    team_project_id: str
    rollup: Dict[str, Any] = Field(default_factory=dict)
    contributors: List[str] = Field(default_factory=list)
    recent_activity: List[Any] = Field(default_factory=list)
    narrative: str = ""
    source_memory_ids: List[str] = Field(default_factory=list)
    model: str
    model_version: str
    prompt_version: str
    generated_at: str
    stale: bool = False


class RelayStatusCount(BaseModel):
    status: str
    count: int


class RelayOutboxSummary(BaseModel):
    id: str
    idempotency_key: str
    target_hub: str
    status: str
    attempts: int
    next_attempt_at: float
    last_error: Optional[str] = None
    created_at: str
    updated_at: str


class RelayQueueSummary(BaseModel):
    id: str
    queue: Literal["item", "aggregate"]
    ref_id: str
    raw_event_id: Optional[str] = None
    status: str
    attempts: int
    next_attempt_at: float
    last_error: Optional[str] = None
    created_at: str
    updated_at: str


class RelayDeadLetterSummary(BaseModel):
    id: str
    queue: Literal["outbox", "item", "aggregate"]
    ref_id: Optional[str] = None
    raw_event_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    target_hub: Optional[str] = None
    attempts: int
    next_attempt_at: float
    last_error: Optional[str] = None
    created_at: str
    updated_at: str


class RelayDigestSummary(BaseModel):
    team_project_id: str
    narrative: str = ""
    source_memory_count: int = 0
    model_version: str
    prompt_version: str
    generated_at: str
    stale: bool = False


class RelayMemorySummary(BaseModel):
    id: str
    source_node_id: str
    source_memory_id: str
    source_project_key: str
    team_project_id: str
    source_version: int
    kind: str
    status: str
    visible: bool = True
    content_preview: str = ""
    title: Optional[str] = None
    abstract: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    updated_at: str
    enriched: bool = False


class RelayAdminOverviewResponse(BaseModel):
    generated_at: str
    outbox_counts: List[RelayStatusCount] = Field(default_factory=list)
    item_queue_counts: List[RelayStatusCount] = Field(default_factory=list)
    aggregate_queue_counts: List[RelayStatusCount] = Field(default_factory=list)
    raw_events: int = 0
    visible_memories: int = 0
    enriched_items: int = 0
    projects: int = 0
    recent_outbox: List[RelayOutboxSummary] = Field(default_factory=list)
    recent_queue: List[RelayQueueSummary] = Field(default_factory=list)
    dead_letters: List[RelayDeadLetterSummary] = Field(default_factory=list)
    recent_digests: List[RelayDigestSummary] = Field(default_factory=list)
    recent_memories: List[RelayMemorySummary] = Field(default_factory=list)


class RelayMaterializeResponse(BaseModel):
    scanned: int = 0
    materialized: int = 0
    deleted: int = 0
    skipped: int = 0
    status: str = "ok"


class RelayPurgeResponse(BaseModel):
    scanned: int = 0
    purged: int = 0
    materialized_deleted: int = 0
    status: str = "ok"


class RelayRetryRequest(BaseModel):
    queue: Literal["all", "outbox", "item", "aggregate"] = "all"
    id: Optional[str] = None
    limit: int = Field(default=1000, ge=1, le=100000)


class RelayRetryResponse(BaseModel):
    retried: int = 0
    outbox: int = 0
    item: int = 0
    aggregate: int = 0
    status: str = "ok"


class RelaySettingValue(BaseModel):
    key: str
    label: str
    value: Optional[str] = None
    configured: bool = False
    source: Literal["env", "db", "default"] = "default"
    env_var: str
    env_pinned: bool = False
    secret: bool = False


class RelayIdentitySummary(BaseModel):
    token_hash_prefix: str
    user_id: str
    source_node_id: str
    display_name: str
    home_domain: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    revoked: bool = False
    created_at: str
    updated_at: str


class RelayHubCheckRequest(BaseModel):
    hub_url: str = Field(min_length=1, max_length=500)
    # Optional token to verify against the hub. Empty → the server falls back to
    # the stored personal-node hub token, so "Check Hub" validates the token
    # that's actually configured even when the input field is masked.
    token: Optional[str] = Field(default=None, max_length=500)


class RelayHubCheckResponse(BaseModel):
    ok: bool
    hub_url: str
    health_url: str
    status_code: Optional[int] = None
    relay: Optional[str] = None
    message: str = ""
    # Token verification: True valid, False rejected (invalid/revoked/no scope),
    # None not checked (no token given, or hub too old to expose /auth/check).
    token_checked: bool = False
    token_ok: Optional[bool] = None
    token_message: str = ""
    node_id: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)


class RelayAuthCheckResponse(BaseModel):
    ok: bool = True
    node_id: str = ""
    user_id: str = ""
    scopes: List[str] = Field(default_factory=list)


class RelayHealthResponse(BaseModel):
    ok: bool = True
    relay: str = "mem-mesh-relay"
    role: str = "hub"


class RelayCategoryPolicy(BaseModel):
    category: str
    # False = this category is opted out of Share/Auto-share (soft block, user
    # controlled). Structurally denylisted categories (e.g. 'task') never
    # appear here at all — they're not a policy choice.
    shared: bool = True


class RelaySettingsResponse(BaseModel):
    generated_at: str
    hub_url: RelaySettingValue
    source_node_id: RelaySettingValue
    default_source_version: int = 1
    hub_token: RelaySettingValue
    llm_provider: RelaySettingValue
    llm_api_key: RelaySettingValue
    llm_model: RelaySettingValue
    llm_base_url: RelaySettingValue
    prompt_version: RelaySettingValue
    identities: List[RelayIdentitySummary] = Field(default_factory=list)
    category_policies: List[RelayCategoryPolicy] = Field(default_factory=list)


class RelaySettingsUpdateRequest(BaseModel):
    hub_url: Optional[str] = Field(default=None, max_length=500)
    source_node_id: Optional[str] = Field(default=None, max_length=200)
    default_source_version: Optional[int] = Field(default=None, ge=0)
    hub_token: Optional[str] = Field(default=None, max_length=500)
    llm_provider: Optional[str] = Field(default=None, max_length=20)
    llm_api_key: Optional[str] = Field(default=None, max_length=500)
    llm_model: Optional[str] = Field(default=None, max_length=200)
    llm_base_url: Optional[str] = Field(default=None, max_length=500)
    prompt_version: Optional[str] = Field(default=None, max_length=100)
    # Explicit set of categories to opt OUT of sharing (replaces the stored
    # set wholesale). None = leave unchanged; [] = clear (share everything
    # not denylisted).
    blocked_categories: Optional[List[str]] = None

    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in ("anthropic", "openai"):
            raise ValueError("llm_provider must be 'anthropic' or 'openai'")
        return normalized


class RelayIdentityCreateRequest(BaseModel):
    token: Optional[str] = Field(default=None, min_length=16, max_length=500)
    user_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    home_domain: Optional[str] = Field(default=None, max_length=300)
    scopes: List[str] = Field(default_factory=lambda: ["read", "write"])

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: List[str]) -> List[str]:
        scopes = [scope for scope in value if scope]
        if not scopes:
            raise ValueError("at least one relay scope is required")
        unknown = set(scopes) - {"read", "write"}
        if unknown:
            raise ValueError(f"unknown relay scope(s): {', '.join(sorted(unknown))}")
        return scopes


class RelayIdentityCreateResponse(BaseModel):
    identity: RelayIdentitySummary
    token: Optional[str] = None
    token_generated: bool = False
    token_hash_prefix: str


class RelayIdentityDeleteResponse(BaseModel):
    ok: bool = True
    token_hash_prefix: str


class RelayIdentityRotateRequest(BaseModel):
    # Optional replacement token; blank → the server generates a secure one
    # (returned once in the response, same as create).
    token: Optional[str] = Field(default=None, min_length=16, max_length=500)


class RelayIdentityUpdateRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    source_node_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    home_domain: Optional[str] = Field(default=None, max_length=300)
    scopes: Optional[List[str]] = None
    revoked: Optional[bool] = None

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        scopes = [scope for scope in value if scope]
        if not scopes:
            raise ValueError("at least one relay scope is required")
        unknown = set(scopes) - {"read", "write"}
        if unknown:
            raise ValueError(f"unknown relay scope(s): {', '.join(sorted(unknown))}")
        return scopes


class RelayInviteSummary(BaseModel):
    """One pairing invite as stored on the hub (code never re-shown)."""

    code_prefix: str
    user_id: str
    display_name: str
    source_node_id: Optional[str] = None
    home_domain: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    expires_at: str
    redeemed_at: Optional[str] = None
    redeemed_source_node_id: Optional[str] = None
    revoked: bool = False
    created_at: str


class RelayInviteCreateRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    # Optional: pin the node id at invite time. Blank → the redeeming node
    # proposes its own id (still subject to the registry uniqueness check).
    source_node_id: Optional[str] = Field(default=None, max_length=200)
    home_domain: Optional[str] = Field(default=None, max_length=300)
    scopes: List[str] = Field(default_factory=lambda: ["read", "write"])
    expires_in_seconds: int = Field(default=86400, ge=60, le=30 * 86400)

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: List[str]) -> List[str]:
        scopes = [scope for scope in value if scope]
        if not scopes:
            raise ValueError("at least one relay scope is required")
        unknown = set(scopes) - {"read", "write"}
        if unknown:
            raise ValueError(f"unknown relay scope(s): {', '.join(sorted(unknown))}")
        return scopes


class RelayInviteCreateResponse(BaseModel):
    invite: RelayInviteSummary
    # The one-time pairing code, shown exactly once at creation.
    code: str


class RelayInviteListResponse(BaseModel):
    invites: List[RelayInviteSummary] = Field(default_factory=list)


class RelayInviteDeleteResponse(BaseModel):
    ok: bool = True
    code_prefix: str


class RelayPairRequest(BaseModel):
    """Hub-side invite redemption (the code itself is the credential)."""

    code: str = Field(min_length=16, max_length=500)
    # Node id the redeeming node proposes; used only when the invite did not
    # pin one at creation time.
    source_node_id: Optional[str] = Field(default=None, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=200)


class RelayPairResponse(BaseModel):
    ok: bool = True
    # Bearer token for this node, returned exactly once.
    token: str
    user_id: str
    source_node_id: str
    display_name: str
    scopes: List[str] = Field(default_factory=list)


class RelayPairConnectRequest(BaseModel):
    """Personal-node side: redeem an invite against a hub and self-configure."""

    hub_url: str = Field(min_length=1, max_length=500)
    code: str = Field(min_length=16, max_length=500)
    source_node_id: Optional[str] = Field(default=None, max_length=200)


class RelayPairConnectResponse(BaseModel):
    ok: bool = True
    hub_url: str
    source_node_id: str
    user_id: str = ""
    scopes: List[str] = Field(default_factory=list)
    message: str = ""
    check: Optional[RelayHubCheckResponse] = None


class RelayShareMemoryRequest(BaseModel):
    source_node_id: Optional[str] = Field(default=None, max_length=200)
    source_version: Optional[int] = Field(default=None, ge=0)
    target_hub: Optional[str] = Field(default=None, max_length=500)
    event_type: RelayEventType = "update"
    status: str = Field(default="active", min_length=1, max_length=50)
    force: bool = False


class RelayShareMemoryResponse(BaseModel):
    outbox_id: str
    status: str = "queued"
    target_hub: str
    source_node_id: str


class RelayShareProjectRequest(BaseModel):
    source_node_id: Optional[str] = Field(default=None, max_length=200)
    source_version: Optional[int] = Field(default=None, ge=0)
    target_hub: Optional[str] = Field(default=None, max_length=500)
    event_type: RelayEventType = "update"
    status: str = Field(default="active", min_length=1, max_length=50)
    force: bool = False


class RelayShareProjectResponse(BaseModel):
    project_id: str
    outbox_ids: List[str] = Field(default_factory=list)
    queued_count: int = 0
    skipped: List[Dict[str, str]] = Field(default_factory=list)
    status: str = "queued"
    target_hub: str
    source_node_id: str


class RelayAutoShareSubscription(BaseModel):
    project_id: str
    enabled: bool = True
    include_relay_origin: bool = False
    target_hub: Optional[str] = None
    source_node_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_synced_at: Optional[str] = None
    last_error: Optional[str] = None


class RelayAutoShareUpdateRequest(BaseModel):
    enabled: bool = True
    include_relay_origin: bool = False


class RelayAutoShareListResponse(BaseModel):
    subscriptions: List[RelayAutoShareSubscription] = Field(default_factory=list)
