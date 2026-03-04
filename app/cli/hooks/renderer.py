"""Template rendering and script writing utilities."""

import re
import stat
from functools import lru_cache
from pathlib import Path

from app.cli.prompts.behaviors import REFLECT_CONFIG
from app.cli.prompts.renderers import (
    VERSION_MARKER,
    render_cursor_followup,
    render_enhanced_stop_prompt,
    render_reflect_prompt,
    render_rules_text,
)

_SHELL_DIR = Path(__file__).parent / "shell"


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
    result = template.replace("__DEFAULT_URL__", url)
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
    return result


def _render_local_template(
    template: str,
    mem_mesh_path: str,
    *,
    project_id: str = "mem-mesh",
) -> str:
    """Replace placeholders for local mode templates."""
    result = template.replace("__MEM_MESH_PATH__", mem_mesh_path)
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
    return result


def _write_script(path: Path, content: str) -> None:
    """Write a shell script and make it executable."""
    unresolved = re.findall(r"__[A-Z0-9_]+__", content)
    if unresolved:
        tokens = ", ".join(sorted(set(unresolved)))
        raise ValueError(f"Unresolved template tokens in {path}: {tokens}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
