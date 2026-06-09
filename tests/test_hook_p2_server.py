"""Unit tests for the P2 server-side correctness fixes.

Covers, at the function level (no subprocess/shell), the three server contracts:

* project_id normalization is a single source of truth and converges every
  entry path (hook ``_project_id`` / schema validator) to one canonical id;
* ``redact_secrets`` masks credentials/PII deterministically and idempotently;
* ``HookService.turns_since_save`` counts UserPromptSubmit turns only.

The shell-vs-HTTP integration parity lives in ``test_hook_consistency.py``.
"""

import pytest

from app.core.redaction import redact_secrets
from app.core.schemas.requests import normalize_project_id
from app.core.services.hook import HookService
from app.web.dashboard.route_modules import hooks as http_hooks

# ───────────────────────── project_id normalization ──────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("/Users/dev/work/OCI.Tools-wt-ABCDEF", "oci-tools"),  # path+worktree+dot
        ("term-mesh-wt-170638b5", "term-mesh"),
        ("term-mesh_wt_170638b5", "term-mesh"),
        ("jmonServerWeb", "jmon-server-web"),  # camelCase
        ("MyProject", "my-project"),
        ("HTMLParser", "html-parser"),  # consecutive caps
        ("oci_tools", "oci-tools"),
        ("OCI-Tools", "oci-tools"),
        ("already-kebab", "already-kebab"),
        # Windows cwd reaching a POSIX server: backslash paths must split to the
        # last segment, not collapse every repo to "unknown".
        ("C:\\Users\\dev\\work\\MyProject", "my-project"),
        ("D:\\repos\\OtherRepo", "other-repo"),
        ("C:\\Users\\dev\\work\\MyProject\\", "my-project"),  # trailing sep
    ],
)
def test_normalize_project_id_canonical(raw, expected):
    assert normalize_project_id(raw, strict=False) == expected


def test_http_project_id_from_windows_path():
    """HTTP-hook _project_id (Path(cwd).name on POSIX keeps the backslash
    string) must still resolve a Windows client cwd to the repo id."""
    assert (
        http_hooks._project_id(cwd="C:\\Users\\dev\\work\\MyProject", explicit=None)
        == "my-project"
    )


def test_normalize_project_id_is_idempotent():
    for raw in ["OCI.Tools-wt-ABCDEF", "jmonServerWeb", "My_Project.X", "a--b__c"]:
        once = normalize_project_id(raw, strict=False)
        assert normalize_project_id(once, strict=False) == once


def test_http_and_schema_paths_converge_on_same_id():
    """The hook entry point and the Pydantic validator must agree."""
    for raw in ["OCI.Tools-wt-ABCDEF", "jmonServerWeb", "Mem_Mesh", "term-mesh"]:
        hook_id = http_hooks._normalize_project_id(raw)
        schema_id = normalize_project_id(raw, strict=False)
        assert hook_id == schema_id


def test_http_project_id_from_worktree_path():
    assert (
        http_hooks._project_id(cwd="/Users/dev/work/OCI.Tools-wt-ABCDEF", explicit=None)
        == "oci-tools"
    )


def test_strict_mode_raises_on_invalid():
    with pytest.raises(ValueError):
        normalize_project_id("", strict=True)
    with pytest.raises(ValueError):
        normalize_project_id("!!!", strict=True)


def test_non_strict_mode_degrades_to_unknown():
    assert normalize_project_id("!!!", strict=False) == "unknown"
    assert normalize_project_id("", strict=False) == "unknown"


def test_none_passes_through():
    assert normalize_project_id(None) is None


# ──────────────────────────────── redaction ──────────────────────────────────


def test_redacts_anthropic_key_bearer_email():
    text = (
        "버그 수정. sk-ant-1234567890abcdef 와 Bearer abc.def.ghi 그리고 "
        "user@example.com 은 마스킹되어야 합니다."
    )
    out = redact_secrets(text)
    assert "<REDACTED>" in out
    assert "sk-ant-1234567890abcdef" not in out
    assert "Bearer abc.def.ghi" not in out
    assert "user@example.com" not in out


def test_redacts_private_key_block_aws_jwt_and_kv():
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAA\n-----END RSA PRIVATE KEY-----\n"
        "AKIAIOSFODNN7EXAMPLE 그리고 "
        "eyJhbGciOi.eyJzdWIiOi.SflKxwRJSM 그리고 "
        "API_KEY=supersecretvalue123"
    )
    out = redact_secrets(text)
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "eyJhbGciOi.eyJzdWIiOi.SflKxwRJSM" not in out
    assert "supersecretvalue123" not in out
    assert "API_KEY=<REDACTED>" in out  # key name kept, value masked


@pytest.mark.parametrize(
    "header,credential",
    [
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("Authorization: ApiKey abc123secretvalue", "abc123secretvalue"),
        (
            'Authorization: Digest username="u", response="deadbeefcafe"',
            "deadbeefcafe",
        ),
        ("Authorization: Bearer abc.def.ghijklmnop", "abc.def.ghijklmnop"),
    ],
)
def test_authorization_header_masks_whole_value_not_just_scheme(header, credential):
    """Regression: the old ``\\S+`` consumed only the scheme word, leaking the
    credential after it (e.g. Basic/ApiKey/Digest). The full value must go."""
    out = redact_secrets(header)
    assert credential not in out
    assert out.strip() == "Authorization: <REDACTED>"


def test_standalone_bearer_still_masked_without_authorization_header():
    out = redact_secrets("sent Bearer xoxb-abcdefghijklmnop in the call")
    assert "xoxb-abcdefghijklmnop" not in out
    assert "Bearer <REDACTED>" in out


def test_authorization_header_redaction_is_idempotent():
    once = redact_secrets("Authorization: Basic dXNlcjpwYXNz")
    assert redact_secrets(once) == once


def test_redaction_is_idempotent():
    text = "token sk-ant-1234567890abcdef and user@example.com"
    once = redact_secrets(text)
    assert redact_secrets(once) == once


def test_redaction_leaves_clean_text_untouched():
    text = "버그를 수정하고 architecture decision을 정리했습니다. 민감정보 없음."
    assert redact_secrets(text) == text


@pytest.mark.parametrize(
    "config",
    [
        "max_tokens=4096",
        "max_tokens: 8192",
        "token_count=5",
        "retry_token_count=5",
        "REFRESH_TOKEN_TTL=3600",
        "ACCESS_TOKEN_TTL=900",
        "session_count=12",
    ],
)
def test_kv_redaction_does_not_false_positive_on_config_keys(config):
    """A non-secret key that merely *contains* a secret word stays intact.

    Regression: substring matching used to mask these, and because redaction
    runs before the dedup hash, distinct config values collapsed to one hash.
    """
    assert redact_secrets(config) == config


@pytest.mark.parametrize(
    "kv",
    [
        "api_key=abc123",
        "password=secret123",
        "PASSWORD=p@ss",
        "PASSWORD=1234",  # key-based: masked regardless of value shape
        "auth_token=abc",
        "access_token: tok",
        "refresh_token=rrr",
        "client_secret=xyz",
        "private_key=zzz",
        "secret=hunter2",
    ],
)
def test_kv_redaction_still_masks_real_secret_keys(kv):
    out = redact_secrets(kv)
    # Masked (value replaced) and the key name + separator preserved.
    assert "<REDACTED>" in out
    assert out != kv
    sep_idx = min(i for i, ch in enumerate(kv) if ch in "=:")
    key = kv[:sep_idx]
    assert out.startswith(key)
    assert out.endswith("<REDACTED>")


def test_kv_redaction_no_false_dedup_hash():
    """Distinct config values must keep distinct dedup hashes after redaction."""
    from app.core.database.models import Memory

    a = redact_secrets("model config max_tokens=4096 done")
    b = redact_secrets("model config max_tokens=8192 done")
    assert a != b
    assert Memory.compute_hash(a) != Memory.compute_hash(b)


# ───────────────────────── turns_since_save counter ──────────────────────────


@pytest.mark.asyncio
async def test_counter_counts_user_prompt_submit_only(temp_db):
    service = HookService(temp_db)
    sid = "s-count"
    for ev, kw in [
        ("UserPromptSubmit", "prompt"),
        ("Stop", "answer"),
        ("Stop", "answer2"),
        ("UserPromptSubmit", "prompt2"),
    ]:
        await service.record_event(
            project_id="p",
            ide_session_id=sid,
            event_name=ev,
            prompt=kw if ev == "UserPromptSubmit" else None,
            assistant_message=kw if ev == "Stop" else None,
            saved_memory=False,
        )
    # 2 UserPromptSubmit, 2 Stop, none saved → Stop must not inflate the count.
    assert await service.turns_since_save(sid) == 2


@pytest.mark.asyncio
async def test_counter_resets_after_save_detected_on_stop(temp_db):
    service = HookService(temp_db)
    sid = "s-reset"
    await service.record_event(
        project_id="p",
        ide_session_id=sid,
        event_name="UserPromptSubmit",
        prompt="q1",
        saved_memory=False,
    )
    # Save detected on a Stop turn (assistant called mcp__mem-mesh__add).
    await service.record_event(
        project_id="p",
        ide_session_id=sid,
        event_name="Stop",
        assistant_message="saved via mcp__mem-mesh__add",
    )
    await service.record_event(
        project_id="p",
        ide_session_id=sid,
        event_name="UserPromptSubmit",
        prompt="q2",
        saved_memory=False,
    )
    # Only the single UserPromptSubmit after the Stop-detected save counts.
    assert await service.turns_since_save(sid) == 1
