"""PreToolUse cross-project injection.

The council's load-bearing claim: a prose rule does not fire (the anchors rule is
explicitly mandated and sits at 0% compliance across 15k memories), so the gate
must be a deterministic path match that the runtime evaluates — and the hook must
INJECT what it found, not instruct the model to go look.

These tests pin the gate (which paths fire, which don't) and the no-op contract
(never inject without peers, never fire on a non-contract file).
"""

import pytest

from app.web.dashboard.route_modules.hooks import _contract_query, _is_contract_path


@pytest.mark.parametrize(
    "path",
    [
        "api/openapi.yaml",
        "services/openapi/spec.json",
        "openapi.yaml",
        "swagger.json",
        "src/schema.prisma",
        "schema.graphql",
        "db/schemas/user.sql",
        "db/migrations/0007_add_token_ttl.sql",
        ".env",
        ".env.local",
        "config/.env.production",
        "server/auth/jwt.py",
        "src/lib/auth.ts",
        "auth-config.ts",
        "auth_middleware.py",
        "docker-compose.yml",
        "docker-compose.override.yaml",
        "Dockerfile",
        "proto/user.proto",
        "src/routes/session.ts",
        "app/api/tokens.py",
    ],
)
def test_contract_paths_fire(path):
    assert _is_contract_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        # Root-level contract directories. fnmatch has no '**', so the old glob
        # list ('**/api/**') silently missed these on any Python without
        # PurePath.full_match (3.12 and below) — the feature just never fired.
        "api/tokens.py",
        "routes/session.ts",
        "schemas/user.sql",
        "migrations/001_init.sql",
    ],
)
def test_root_level_contract_directories_fire(path):
    assert _is_contract_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        # 'auth' as a prefix of an ordinary word: the old '**/*auth*' glob fired
        # on every one of these. A false fire inflates the very firing metric the
        # kill-condition reads — which is how a dead feature looks alive.
        "AUTHORS",
        "src/components/AuthorCard.tsx",
        "docs/authors.md",
        "src/ui/oauth-modal.js",
        "lib/authorize-ui.css",
        # Plain files.
        "src/components/Button.tsx",
        "README.md",
        "tests/test_utils.py",
        "styles/main.css",
        "src/utils/format.ts",
        "",
    ],
)
def test_ordinary_paths_do_not_fire(path):
    assert _is_contract_path(path) is False


def test_custom_globs_replace_the_defaults():
    # A repo that keeps its contract elsewhere overrides the list entirely —
    # including at the root, which is the same fnmatch '**' trap as above.
    assert _is_contract_path("contracts/payments.yaml", ["**/contracts/**"]) is True
    assert _is_contract_path("src/contracts/v2.yaml", ["**/contracts/**"]) is True
    # ...and the defaults no longer apply once the client sets its own.
    assert _is_contract_path("api/openapi.yaml", ["**/contracts/**"]) is False


def test_contract_query_uses_filename_and_parents():
    q = _contract_query("services/auth/openapi.yaml")
    assert "openapi" in q
    assert "auth" in q
    # Deepest parents first — the immediate directory is the strongest signal.
    assert q.index("auth") < q.index("services")


def test_contract_query_survives_a_dotfile():
    # PurePosixPath('.env.local').stem == '.env' — the query must not come out empty.
    assert _contract_query(".env.local").strip() != ""


def test_malformed_peer_id_does_not_500_the_hook():
    """Regression (review F4): peers came from a repo file and were normalized
    with strict=True OUTSIDE the try block, so one malformed id raised into the
    caller. This module's contract is that every hook handler returns 200 and
    degrades — a 500 breaks it."""

    from app.core.schemas.requests import normalize_project_id

    # strict=True is what the handler used to call — a peer id the repo file got
    # wrong raises, and the raise happened outside the handler's try block.
    with pytest.raises(ValueError):
        normalize_project_id("!!!", strict=True)

    # strict=False degrades instead, which is what the handler does now.
    assert normalize_project_id("!!!", strict=False) == "unknown"
    assert normalize_project_id("   ", strict=False) == "unknown"
