"""Template rendering and script writing utilities."""

import re
import shlex
import stat
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from app.cli.hooks.hook_log import HOOK_LOG_BLOCK
from app.cli.hooks.json_ops import _atomic_write_text
from app.cli.hooks.keywords import KEYWORD_MATCHER_BLOCK
from app.cli.prompts.behaviors import REFLECT_CONFIG
from app.cli.prompts.renderers import (
    VERSION_MARKER,
    render_cursor_followup,
    render_enhanced_stop_prompt,
    render_reflect_prompt,
    render_rules_text,
)

_SHELL_DIR = Path(__file__).parent / "shell"

# Shell metacharacters that enable command injection / chaining. A value
# containing any of these has no place in a real API URL or install path, and
# must never reach a shell template even after shlex.quote — quoting can be
# defeated when a template wraps the placeholder in its own double quotes
# (e.g. MEM_MESH_PATH="<token>"). Rejecting up front is the primary defense;
# shlex.quote + unquoted placeholders (see templates) are defense in depth.
_SHELL_METACHARS = frozenset("$`\"'\\;|&<>(){}\n\r\t")


def _reject_shell_metachars(value: str, label: str) -> None:
    """Raise ValueError if ``value`` contains shell-dangerous characters."""
    if any(ch < " " for ch in value):
        raise ValueError(f"{label} contains control characters")
    bad = sorted(set(value) & _SHELL_METACHARS)
    if bad:
        raise ValueError(f"{label} contains unsafe shell characters: {bad!r}")


# Characters that stay active inside a double-quoted shell string. project_id is
# substituted (via render_rules_text / render_cursor_followup) into templates
# that wrap the text in double quotes (e.g. RULES_TEXT="..."), so a project_id
# like ``$(cmd)`` or ```cmd`` would execute. The text is multi-line markdown and
# cannot be single-quoted, so the project_id itself is validated here.
_DQUOTE_DANGEROUS = frozenset('$`"\\')


def _safe_project_id(project_id: str) -> str:
    """Reject a project_id that could break out of a double-quoted shell string."""
    if not isinstance(project_id, str):
        raise ValueError("project_id must be a string")
    if any(ch < " " for ch in project_id):
        raise ValueError("project_id contains control characters")
    bad = sorted(set(project_id) & _DQUOTE_DANGEROUS)
    if bad:
        raise ValueError(f"project_id contains unsafe shell characters: {bad!r}")
    return project_id


def _shell_safe_url(url: str) -> str:
    """Validate a hook API URL and return a shell-safe (quoted) form.

    The URL is interpolated into shell templates (e.g. ``echo <url>``), so an
    unvalidated value containing ``$()``, backticks, ``;`` etc. could execute
    arbitrary commands when the hook runs. Reject anything that is not a plain
    ``http(s)://host`` URL, reject shell metacharacters outright, then quote
    with :func:`shlex.quote` for defense in depth. A clean URL quotes to
    itself, so normal installs are unchanged.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("hook API URL must be a non-empty string")
    candidate = url.strip()
    _reject_shell_metachars(candidate, "hook API URL")
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"invalid hook API URL: {url!r} (expected http(s)://host[:port])"
        )
    return shlex.quote(candidate)


def _shell_safe_local_path(path: str) -> str:
    """Validate a local mem-mesh path and return a shell-safe (quoted) form.

    The path is interpolated into shell templates, so it is resolved
    (``Path.resolve``), checked for shell metacharacters (rejected outright),
    and quoted with :func:`shlex.quote`. A missing path is a non-fatal warning
    rather than an error, so a first-run install can proceed before the
    directory exists.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("local mem-mesh path must be a non-empty string")
    _reject_shell_metachars(path, "local mem-mesh path")
    resolved = Path(path).expanduser().resolve()
    _reject_shell_metachars(str(resolved), "resolved local mem-mesh path")
    if not resolved.exists():
        print(
            f"WARNING: local mem-mesh path does not exist: {resolved}",
            file=sys.stderr,
        )
    return shlex.quote(str(resolved))


@lru_cache(maxsize=None)
def _load_template(name: str) -> str:
    """Load a shell template from the shell/ directory."""
    return (_SHELL_DIR / name).read_text(encoding="utf-8")


def _render_template(
    template: str,
    url: str,
    *,
    source_tag: str = "claude-code-hook",
    ide_tag: str = "claude",
    client_tag: str = "claude_code",
    project_id: str = "mem-mesh",
) -> str:
    """Replace all placeholders in a template string."""
    project_id = _safe_project_id(project_id)
    result = template.replace("__DEFAULT_URL__", _shell_safe_url(url))
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__SOURCE_TAG__", source_tag)
    result = result.replace("__IDE_TAG__", ide_tag)
    result = result.replace("__CLIENT_TAG__", client_tag)
    # Inject renderer-generated text
    result = result.replace("__RULES_TEXT__", render_rules_text(project_id))
    result = result.replace("__FOLLOWUP_MSG__", render_cursor_followup(project_id))
    # Reflect hook placeholders
    result = result.replace("__REFLECT_PROMPT__", render_reflect_prompt())
    result = result.replace("__REFLECT_MODEL__", REFLECT_CONFIG.model)
    result = result.replace("__REFLECT_MAX_TOKENS__", str(REFLECT_CONFIG.max_tokens))
    result = result.replace("__REFLECT_TIMEOUT__", str(REFLECT_CONFIG.timeout_seconds))
    # Enhanced stop hook prompt
    result = result.replace("__ENHANCED_PROMPT__", render_enhanced_stop_prompt())
    # Keyword matcher block (single source of truth)
    result = result.replace("__KEYWORD_MATCHER__", KEYWORD_MATCHER_BLOCK)
    # Opt-in hook logging block (single source of truth)
    result = result.replace("__HOOK_LOG__", HOOK_LOG_BLOCK)
    return result


def _render_local_template(
    template: str,
    mem_mesh_path: str,
    *,
    project_id: str = "mem-mesh",
) -> str:
    """Replace placeholders for local mode templates."""
    project_id = _safe_project_id(project_id)
    result = template.replace(
        "__MEM_MESH_PATH__", _shell_safe_local_path(mem_mesh_path)
    )
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__RULES_TEXT__", render_rules_text(project_id))
    result = result.replace("__FOLLOWUP_MSG__", render_cursor_followup(project_id))
    # Reflect hook placeholders
    result = result.replace("__REFLECT_PROMPT__", render_reflect_prompt())
    result = result.replace("__REFLECT_MODEL__", REFLECT_CONFIG.model)
    result = result.replace("__REFLECT_MAX_TOKENS__", str(REFLECT_CONFIG.max_tokens))
    result = result.replace("__REFLECT_TIMEOUT__", str(REFLECT_CONFIG.timeout_seconds))
    # Enhanced stop hook prompt
    result = result.replace("__ENHANCED_PROMPT__", render_enhanced_stop_prompt())
    # Keyword matcher block (single source of truth)
    result = result.replace("__KEYWORD_MATCHER__", KEYWORD_MATCHER_BLOCK)
    # Opt-in hook logging block (single source of truth)
    result = result.replace("__HOOK_LOG__", HOOK_LOG_BLOCK)
    return result


def _write_script(path: Path, content: str) -> None:
    """Write a shell script and make it executable (atomically)."""
    unresolved = re.findall(r"__[A-Z0-9_]+__", content)
    if unresolved:
        tokens = ", ".join(sorted(set(unresolved)))
        raise ValueError(f"Unresolved template tokens in {path}: {tokens}")
    _atomic_write_text(
        path,
        content,
        mode=stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
    )
