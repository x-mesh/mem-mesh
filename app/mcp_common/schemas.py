"""
MCP Tool Schemas - JSON Schema 정의.

Pure MCP 구현에서 tools/list 응답에 사용됩니다.
FastMCP는 자동으로 스키마를 생성하지만, 일관성을 위해 여기서 정의합니다.
"""

from typing import Any, Dict, List

from .descriptions import TOOL_DESCRIPTIONS

# Valid category list
VALID_CATEGORIES = [
    "task",
    "bug",
    "idea",
    "decision",
    "incident",
    "code_snippet",
    "git-history",
]

# Valid search mode list
VALID_SEARCH_MODES = ["hybrid", "exact", "semantic", "fuzzy"]

# Git anchors: client-collected metadata pinning a memory to the commit/files/
# branch it was written against. Metadata only — never embedded or searched.
ANCHORS_SCHEMA = {
    "type": "object",
    "description": (
        "Git anchors the client collected for this memory. When saving a "
        "code/commit-related memory in a git repo, pass `git rev-parse HEAD` "
        "and the relevant relative file paths. Omit if not a git repository."
    ),
    "properties": {
        "commit_hash": {
            "type": "string",
            "description": "Commit hash (7-64 hex chars, e.g. from `git rev-parse HEAD`)",
            "pattern": "^[0-9a-fA-F]{7,64}$",
        },
        "file_paths": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "description": "Relative file paths (no absolute paths, no '..')",
            "maxItems": 20,
        },
        "branch": {
            "type": "string",
            "description": "Git branch name (optional)",
            "minLength": 1,
        },
        "file_hashes": {
            "type": "object",
            "description": (
                "Per-file content hashes as {relative_path: 'algo:hexdigest'} "
                "(e.g. {'app/core/x.py': 'xxh64:1a2b3c...'}). Lets the client "
                "verify staleness per file: unchanged file content means the "
                "memory stays fresh even when commit_hash is old."
            ),
            "additionalProperties": {
                "type": "string",
                "pattern": "^[a-z0-9_]+:[0-9a-fA-F]{8,128}$",
            },
            "maxProperties": 20,
        },
    },
    "additionalProperties": False,
}

# Server info imported from central module


def get_tool_schemas() -> List[Dict[str, Any]]:
    """MCP tools/list 응답용 스키마 반환"""
    return [
        {
            "name": "add",
            "description": TOOL_DESCRIPTIONS["add"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Memory content (100-50000 characters)",
                        "minLength": 100,
                        "maxLength": 50000,
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier (optional)",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "category": {
                        "type": "string",
                        "description": "Memory category",
                        "default": "task",
                        "enum": VALID_CATEGORIES,
                    },
                    "source": {
                        "type": "string",
                        "description": "Memory source",
                        "default": "mcp",
                        "maxLength": 50,
                    },
                    "client": {
                        "type": "string",
                        "description": "Client tool name (e.g. cursor, kiro, claude_code)",
                        "maxLength": 50,
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 50},
                        "description": "Memory tags",
                        "maxItems": 20,
                    },
                    "anchors": ANCHORS_SCHEMA,
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
        {
            "name": "search",
            "description": TOOL_DESCRIPTIONS["search"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query. Use empty string '' to get recent memories without search. Korean time expressions (이번주, 지난달) are auto-detected.",
                        "maxLength": 500,
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project filter",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "category": {
                        "type": "string",
                        "description": "Category filter",
                        "enum": VALID_CATEGORIES,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (1-20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                    "recency_weight": {
                        "type": "number",
                        "description": "Recency weight (0.0-1.0)",
                        "default": 0.0,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "response_format": {
                        "type": "string",
                        "description": "Response format: minimal (IDs only), compact (summaries), standard (full), full (complete)",
                        "default": "standard",
                        "enum": ["minimal", "compact", "standard", "full"],
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Time range shortcut: today, yesterday, this_week, last_week, this_month, last_month, this_quarter",
                        "enum": [
                            "today",
                            "yesterday",
                            "this_week",
                            "last_week",
                            "this_month",
                            "last_month",
                            "this_quarter",
                        ],
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "temporal_mode": {
                        "type": "string",
                        "description": "Temporal mode: filter (only in range), boost (prioritize in range, default), decay (score decreases with age)",
                        "default": "boost",
                        "enum": ["filter", "boost", "decay"],
                    },
                    "scope": {
                        "type": "string",
                        "description": "Search scope: local (this node only, default), hub (team hub only), all (local + hub fused; hub outage degrades to local)",
                        "default": "local",
                        "enum": ["local", "hub", "all"],
                    },
                    "anchored_path": {
                        "type": "string",
                        "description": (
                            "Only memories git-anchored to this repo-relative "
                            "file/directory prefix (e.g. 'app/core/'). "
                            "Directory-boundary match; forces scope=local."
                        ),
                        "maxLength": 500,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "context",
            "description": TOOL_DESCRIPTIONS["context"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID (full 36-char UUID from add/search response). Truncated/short ids are NOT accepted.",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Search depth (1-5)",
                        "default": 2,
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project filter",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "response_format": {
                        "type": "string",
                        "description": "Response format: compact (summaries), standard (full)",
                        "default": "standard",
                        "enum": ["compact", "standard", "full"],
                    },
                    "ids": {
                        "type": "array",
                        "description": (
                            "Batch mode: fetch up to 10 memories in one call "
                            "(full 36-char UUIDs). Missing ids are returned in "
                            "not_found instead of failing the batch. Provide "
                            "either memory_id or ids."
                        ),
                        "items": {
                            "type": "string",
                            "pattern": "^[a-zA-Z0-9_-]+$",
                            "maxLength": 100,
                        },
                        "minItems": 1,
                        "maxItems": 10,
                    },
                },
                "anyOf": [
                    {"required": ["memory_id"]},
                    {"required": ["ids"]},
                ],
                "additionalProperties": False,
            },
        },
        {
            "name": "update",
            "description": TOOL_DESCRIPTIONS["update"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID to update (full 36-char UUID from add/search response). Truncated/short ids are NOT accepted.",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "content": {
                        "type": "string",
                        "description": "New content (100-50000 characters)",
                        "minLength": 100,
                        "maxLength": 50000,
                    },
                    "category": {
                        "type": "string",
                        "description": "New category",
                        "enum": VALID_CATEGORIES,
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 50},
                        "description": "New tags",
                        "maxItems": 20,
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "delete",
            "description": TOOL_DESCRIPTIONS["delete"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID to delete (full 36-char UUID from add/search response). Truncated/short ids are NOT accepted.",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "stats",
            "description": TOOL_DESCRIPTIONS["stats"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project filter",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date filter (YYYY-MM-DD)",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date filter (YYYY-MM-DD)",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                },
                "additionalProperties": False,
            },
        },
    ]


def get_pin_tool_schemas() -> List[Dict[str, Any]]:
    """Pin/Session 관련 MCP tools/list 응답용 스키마 반환"""
    return [
        {
            "name": "pin_add",
            "description": TOOL_DESCRIPTIONS["pin_add"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Pin content describing the task or work item",
                        "minLength": 10,
                        "maxLength": 10000,
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "importance": {
                        "type": "integer",
                        "description": "Importance score (1-5). Auto-determined if not provided.",
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 50},
                        "description": "Pin tags",
                        "maxItems": 10,
                    },
                    "staging": {
                        "type": "boolean",
                        "description": "Mark pin as staging (shown in separate staging_pins section on session_resume)",
                        "default": False,
                    },
                },
                "required": ["content", "project_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "pin_complete",
            "description": TOOL_DESCRIPTIONS["pin_complete"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pin_id": {
                        "type": "string",
                        "description": "Pin ID to complete",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "promote": {
                        "type": "boolean",
                        "description": "If true, also promote to permanent memory (saves a round-trip)",
                        "default": False,
                    },
                    "category": {
                        "type": "string",
                        "description": "Memory category when promoting",
                        "enum": [
                            "task",
                            "decision",
                            "bug",
                            "incident",
                            "idea",
                            "code_snippet",
                        ],
                        "default": "task",
                    },
                },
                "required": ["pin_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "pin_promote",
            "description": TOOL_DESCRIPTIONS["pin_promote"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pin_id": {
                        "type": "string",
                        "description": "Pin ID to promote to memory",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "category": {
                        "type": "string",
                        "description": "Memory category (default: task)",
                        "enum": [
                            "task",
                            "bug",
                            "idea",
                            "decision",
                            "incident",
                            "code_snippet",
                        ],
                        "default": "task",
                    },
                    "anchors": ANCHORS_SCHEMA,
                },
                "required": ["pin_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "pin_list",
            "description": TOOL_DESCRIPTIONS["pin_list"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Filter by a specific session (optional)",
                        "maxLength": 100,
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status",
                        "enum": ["open", "in_progress", "completed"],
                    },
                    "min_importance": {
                        "type": "integer",
                        "description": "Minimum importance score (1-5)",
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 50},
                        "description": "Filter by tags (AND condition)",
                        "maxItems": 10,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of pins to return",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "include_stats": {
                        "type": "boolean",
                        "description": "Include pin statistics in the response",
                        "default": False,
                    },
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "pin_get",
            "description": TOOL_DESCRIPTIONS["pin_get"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pin_id": {
                        "type": "string",
                        "description": "Full pin ID (36-char UUID) to retrieve",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                },
                "required": ["pin_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "session_resume",
            "description": TOOL_DESCRIPTIONS["session_resume"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "expand": {
                        "description": "Expand mode: false=compact(80 chars), true=full content, 'smart'=4-tier matrix based on status×importance (recommended). Smart tiers: T1(active+important)=full, T2(active+normal)=200chars, T3(completed+important)=80chars, T4(completed+normal)=id only",
                        "default": False,
                        "oneOf": [
                            {"type": "boolean"},
                            {"type": "string", "enum": ["smart"]},
                        ],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of pins to return",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "session_end",
            "description": TOOL_DESCRIPTIONS["session_end"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "summary": {
                        "type": "string",
                        "description": "Session summary (auto-generated if not provided)",
                        "maxLength": 500,
                    },
                    "auto_complete_pins": {
                        "description": "Pin auto-complete strategy: 'none'(default), 'in_progress'(complete active only, keep open), 'all'(complete everything). Boolean also accepted (false=none, true=all).",
                        "default": "none",
                        "oneOf": [
                            {"type": "boolean"},
                            {
                                "type": "string",
                                "enum": ["none", "in_progress", "all"],
                            },
                        ],
                    },
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
    ]


def get_all_tool_schemas() -> List[Dict[str, Any]]:
    """모든 MCP tool 스키마 반환 (memory + pin/session + batch + relations + review + doc proposal + anchor)"""
    return (
        get_tool_schemas()
        + get_pin_tool_schemas()
        + get_batch_tool_schemas()
        + get_relation_tool_schemas()
        + get_review_tool_schemas()
        + get_doc_proposal_tool_schemas()
        + get_anchor_tool_schemas()
    )


def get_anchor_tool_schemas() -> List[Dict[str, Any]]:
    """Anchor-verification MCP tools/list 응답용 스키마 반환.

    검증 주체는 클라이언트(에이전트)다: 서버는 git 접근이 없어 앵커의 file_paths 존재·
    commit 도달성을 확인할 수 없으므로, 로컬에서 확인한 결과만 받아 stale 게이트에
    반영한다.
    """
    return [
        {
            "name": "report_anchor_status",
            "description": TOOL_DESCRIPTIONS["report_anchor_status"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": (
                            "Memory ID (full 36-char UUID from add/search/get) "
                            "whose anchors you verified locally"
                        ),
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "status": {
                        "type": "string",
                        "description": (
                            "Verification verdict: 'fresh' (file_paths exist and "
                            "commit reachable) or 'stale' (files gone / commit "
                            "unreachable)"
                        ),
                        "enum": ["fresh", "stale"],
                    },
                    "detail": {
                        "type": "string",
                        "description": (
                            "Optional note on what failed (e.g. which file or "
                            "commit) — logged, not stored on the memory"
                        ),
                        "maxLength": 500,
                    },
                },
                "required": ["memory_id", "status"],
                "additionalProperties": False,
            },
        },
    ]


def get_doc_proposal_tool_schemas() -> List[Dict[str, Any]]:
    """Doc proposal(문서 승격) MCP tools/list 응답용 스키마 반환.

    적용은 클라이언트(에이전트)가 하고 서버는 상태 전이만 관리한다: doc_proposals로
    승인된 제안을 조회해 로컬 파일에 적용한 뒤 doc_proposal_applied로 보고한다.
    """
    return [
        {
            "name": "doc_proposals",
            "description": TOOL_DESCRIPTIONS["doc_proposals"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by proposal status (default: approved)",
                        "enum": ["pending", "approved", "applied", "rejected"],
                        "default": "approved",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of proposals to return",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 200,
                    },
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "doc_proposal_applied",
            "description": TOOL_DESCRIPTIONS["doc_proposal_applied"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "Full doc proposal ID to mark applied",
                        "maxLength": 100,
                    },
                },
                "required": ["proposal_id"],
                "additionalProperties": False,
            },
        },
    ]


def get_batch_tool_schemas() -> List[Dict[str, Any]]:
    """Batch operations MCP tools/list 응답용 스키마 반환"""
    return [
        {
            "name": "batch_operations",
            "description": TOOL_DESCRIPTIONS["batch_operations"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "description": "List of operation dictionaries with 'type' and parameters",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": "Operation type",
                                    "enum": ["add", "search", "pin_add"],
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Memory content (for 'add' operations) or Pin content (for 'pin_add')",
                                    "minLength": 10,
                                    "maxLength": 50000,
                                },
                                "query": {
                                    "type": "string",
                                    "description": "Search query (for 'search' operations). Use empty string for recent memories.",
                                    "maxLength": 500,
                                },
                                "project_id": {
                                    "type": "string",
                                    "description": "Project identifier",
                                    "pattern": "^[a-zA-Z0-9_-]+$",
                                    "maxLength": 100,
                                },
                                "category": {
                                    "type": "string",
                                    "description": "Category",
                                    "enum": VALID_CATEGORIES,
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 50,
                                    },
                                    "description": "Tags",
                                    "maxItems": 20,
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum results (for 'search' operations)",
                                    "default": 5,
                                    "minimum": 1,
                                    "maximum": 20,
                                },
                                "anchored_path": {
                                    "type": "string",
                                    "description": (
                                        "anchors.file_paths prefix filter "
                                        "(for 'search' operations)"
                                    ),
                                    "maxLength": 500,
                                },
                                "importance": {
                                    "type": "integer",
                                    "description": "Importance score (for 'pin_add' operations). Auto-determined if not provided.",
                                    "minimum": 1,
                                    "maximum": 5,
                                },
                            },
                            "required": ["type"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                        "maxItems": 50,
                    },
                },
                "required": ["operations"],
                "additionalProperties": False,
            },
        },
    ]


# Valid relation type list
VALID_RELATION_TYPES = [
    "related",
    "parent",
    "child",
    "supersedes",
    "references",
    "depends_on",
    "similar",
]


def get_relation_tool_schemas() -> List[Dict[str, Any]]:
    """Memory Relations MCP tools/list 응답용 스키마 반환"""
    return [
        {
            "name": "link",
            "description": TOOL_DESCRIPTIONS["link"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source memory ID",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Target memory ID",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "relation_type": {
                        "type": "string",
                        "description": "Type of relation",
                        "default": "related",
                        "enum": VALID_RELATION_TYPES,
                    },
                    "strength": {
                        "type": "number",
                        "description": "Relation strength (0.0-1.0)",
                        "default": 1.0,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata for the relation",
                        "additionalProperties": True,
                    },
                },
                "required": ["source_id", "target_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "unlink",
            "description": TOOL_DESCRIPTIONS["unlink"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source memory ID",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Target memory ID",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "relation_type": {
                        "type": "string",
                        "description": "Specific relation type to remove (optional - removes all if not specified)",
                        "enum": VALID_RELATION_TYPES,
                    },
                },
                "required": ["source_id", "target_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_links",
            "description": TOOL_DESCRIPTIONS["get_links"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID to get relations for (full 36-char UUID from add/search response). Truncated/short ids are NOT accepted.",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100,
                    },
                    "relation_type": {
                        "type": "string",
                        "description": "Filter by relation type (optional)",
                        "enum": VALID_RELATION_TYPES,
                    },
                    "direction": {
                        "type": "string",
                        "description": "Relation direction filter",
                        "default": "both",
                        "enum": ["outgoing", "incoming", "both"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum relations to return",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        },
    ]


def get_review_tool_schemas() -> List[Dict[str, Any]]:
    """Weekly review MCP tool 스키마 반환"""
    return [
        {
            "name": "weekly_review",
            "description": TOOL_DESCRIPTIONS["weekly_review"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "maxLength": 100,
                        "pattern": "^[a-zA-Z0-9_-]+$",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to review (default: 7)",
                        "default": 7,
                        "minimum": 1,
                        "maximum": 90,
                    },
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
    ]
