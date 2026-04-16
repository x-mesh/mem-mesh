"""Packaging smoke tests.

These tests guard against regressions where new non-Python assets get added
to the source tree without being included in the wheel. Every file referenced
here is loaded at runtime by the server or the hook installer — if it's not
packaged, users hit FileNotFoundError on first use.

Run these tests before every release; they are cheap and catch the
"worked locally, broke in uvx" class of bug.
"""

from pathlib import Path

import pytest


# ---- Hook templates ----------------------------------------------------------


def test_shell_hook_templates_packaged():
    """All shell templates referenced by the hook installer must be on disk."""
    from app.cli.hooks.renderer import _SHELL_DIR

    required = [
        "stop.sh",
        "stop-decide.sh",
        "enhanced-stop.sh",
        "session-start.sh",
        "session-end.sh",
        "precompact.sh",
        "user-prompt-submit.sh",
        "subagent-start.sh",
        "subagent-stop.sh",
        "task-completed.sh",
        "reflect.sh",
        "kiro-stop.sh",
        "cursor-session-start.sh",
        "cursor-stop.sh",
        # local-mode counterparts
        "local-stop.sh",
        "local-session-start.sh",
        "local-session-end.sh",
        "local-precompact.sh",
        "local-enhanced-stop.sh",
        "local-user-prompt-submit.sh",
        "local-subagent-start.sh",
        "local-subagent-stop.sh",
        "local-task-completed.sh",
        "local-reflect.sh",
    ]

    missing = [name for name in required if not (_SHELL_DIR / name).is_file()]
    assert not missing, f"Shell templates missing from package: {missing}"


def test_hook_template_loading_works():
    """Ensure the hook-template loader can actually open a template."""
    from app.cli.hooks.renderer import _load_template

    content = _load_template("stop.sh")
    assert content.startswith("#!") or len(content) > 0


# ---- Web assets --------------------------------------------------------------


def test_web_templates_packaged():
    from app.web.app import _WEB_ROOT

    templates_dir = _WEB_ROOT / "templates"
    assert templates_dir.is_dir(), f"Missing: {templates_dir}"
    assert (templates_dir / "index.html").is_file(), "index.html missing"


def test_web_static_packaged():
    from app.web.app import _WEB_ROOT

    static_dir = _WEB_ROOT / "static"
    assert static_dir.is_dir()
    assert (static_dir / "css" / "main.css").is_file(), "main.css missing"
    assert (static_dir / "js" / "main.js").is_file(), "main.js missing"


def test_dashboard_paths_resolve_to_package():
    """Both dashboard modules must point templates at the same package-relative dir."""
    from app.web.dashboard.app import _WEB_ROOT as dash_root
    from app.web.dashboard.pages import _WEB_ROOT as pages_root
    from app.web.app import _WEB_ROOT as web_root

    assert dash_root == web_root == pages_root, (
        f"Template roots disagree: dashboard.app={dash_root}, "
        f"dashboard.pages={pages_root}, web.app={web_root}"
    )


# ---- Rules directory ---------------------------------------------------------


def test_rules_index_packaged():
    from app.web.dashboard.routes import _rules_index_path

    idx = _rules_index_path()
    assert idx.is_file(), f"rules/index.json missing: {idx}"


def test_all_referenced_rule_files_exist():
    """Every rule entry in index.json must resolve to a file that exists."""
    import json

    from app.web.dashboard.routes import (
        _load_rules_index,
        _resolve_rule_path,
    )

    index = _load_rules_index()
    missing = []
    for rule in index.get("rules", []):
        try:
            path = _resolve_rule_path(rule)
        except (ValueError, KeyError) as exc:
            missing.append((rule.get("id"), str(exc)))
            continue
        if not path.is_file():
            missing.append((rule.get("id"), f"file not found: {path}"))
    assert not missing, f"Rule files missing: {missing}"


# ---- Default paths -----------------------------------------------------------


def test_default_db_path_is_absolute_and_outside_cwd(tmp_path, monkeypatch):
    """Default DB path must NOT depend on CWD — the classic uvx footgun."""
    from app.core.config import _default_db_path

    monkeypatch.chdir(tmp_path)  # simulate running from a random directory
    path = Path(_default_db_path())
    assert path.is_absolute(), f"Default DB path must be absolute: {path}"
    assert tmp_path not in path.parents, (
        f"Default DB path {path} leaks into CWD {tmp_path}"
    )


# ---- Optional: full import surface ------------------------------------------


@pytest.mark.parametrize(
    "module",
    [
        "app.cli.main",
        "app.cli.install_hooks",
        "app.cli.hooks.installer",
        "app.cli.mcp_config",
        "app.cli.onboarding",
        "app.web.app",
        "app.web.dashboard.app",
        "app.web.dashboard.pages",
        "app.web.dashboard.routes",
        "app.mcp_stdio.__main__",
        "app.mcp_stdio_pure.__main__",
    ],
)
def test_public_modules_importable(module):
    """These modules must import cleanly with only declared dependencies."""
    import importlib

    importlib.import_module(module)
