"""mem-mesh hook installation package.

Re-exports key symbols for backward compatibility with existing imports
like ``from app.cli.hooks import templates, constants, installer``.
"""

from app.cli.hooks.constants import (  # noqa: F401
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    DEFAULT_URL,
    HOME,
    HOOK_PROFILES,
    KIRO_HOOKS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.installer import (  # noqa: F401
    CLAUDE_HOOKS_SETTINGS,
    _build_claude_hooks_settings,
    _build_cursor_hooks_settings,
    _install_claude,
    _install_cursor,
    _install_kiro,
)
from app.cli.hooks.json_ops import (  # noqa: F401
    _count_mem_mesh_hook_entries,
    _is_mem_mesh_entry,
    _is_mem_mesh_hook,
    _merge_hook_entries,
    _merge_json_settings,
    _remove_hook_event,
    _remove_json_key,
    _remove_kiro_mem_mesh_hooks,
    _remove_mem_mesh_hooks_from_json,
)
from app.cli.hooks.renderer import (  # noqa: F401
    _render_local_template,
    _render_template,
    _write_script,
)
from app.cli.hooks.status import (  # noqa: F401
    _check_script,
    _check_script_version,
    _detect_profile,
    _extract_url_from_script,
    _has_prompt_stop_hook,
    cmd_status,
)
from app.cli.hooks.sync import (  # noqa: F401
    _find_project_root,
    _sync_cursor_hooks,
    _sync_kiro_hooks,
    cmd_sync_project,
)
from app.cli.hooks.templates import (  # noqa: F401
    CURSOR_SESSION_START_TEMPLATE,
    CURSOR_STOP_TEMPLATE,
    ENHANCED_STOP_HOOK_TEMPLATE,
    KIRO_STOP_HOOK_TEMPLATE,
    LOCAL_ENHANCED_STOP_HOOK_TEMPLATE,
    LOCAL_REFLECT_HOOK_TEMPLATE,
    LOCAL_SESSION_START_HOOK_TEMPLATE,
    LOCAL_STOP_HOOK_TEMPLATE,
    REFLECT_HOOK_TEMPLATE,
    SESSION_START_HOOK_TEMPLATE,
    STOP_DECIDE_HOOK_TEMPLATE,
    STOP_HOOK_TEMPLATE,
)
from app.cli.hooks.uninstaller import (  # noqa: F401
    _uninstall_claude,
    _uninstall_cursor,
    _uninstall_kiro,
)
