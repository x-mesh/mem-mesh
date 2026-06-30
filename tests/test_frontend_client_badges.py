"""Regression tests for shared client badge styling."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT_TOKENS = (
    "--client-claude",
    "--client-claude-desktop",
    "--client-codex",
    "--client-cursor",
    "--client-kiro",
    "--client-web",
    "--client-vscode",
    "--client-antigravity",
    "--client-agy",
    "--client-generic",
    "--client-unknown",
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _luminance(hex_color: str) -> float:
    values = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        value / 12.92
        if value <= 0.03928
        else ((value + 0.055) / 1.055) ** 2.4
        for value in values
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_shared_client_badge_palette_covers_known_clients() -> None:
    base_css = _read("app/web/static/css/modules/base.css")
    components_css = _read("app/web/static/css/modules/components.css")
    dashboard_js = _read("app/web/static/js/pages/dashboard.js")

    for token in CLIENT_TOKENS:
        assert token in base_css

    for class_name in (
        ".client-claude_code",
        ".client-codex",
        ".client-cursor",
        ".client-kiro",
        ".client-web",
        ".client-vscode",
        ".client-antigravity",
        ".client-agy",
    ):
        assert class_name in components_css

    assert "agy: '#0f766e'" in dashboard_js


def test_client_badge_palette_has_white_text_contrast() -> None:
    base_css = _read("app/web/static/css/modules/base.css")

    for token in CLIENT_TOKENS:
        match = re.search(rf"{re.escape(token)}:\s*(#[0-9a-fA-F]{{6}});", base_css)
        assert match, token
        assert _contrast(match.group(1), "#ffffff") >= 4.5, token


def test_client_badge_surfaces_use_shared_tokens() -> None:
    for path in (
        "app/web/static/css/modules/dashboard.css",
        "app/web/static/js/pages/memories.js",
        "app/web/static/js/components/memory-card.js",
        "app/web/static/js/pages/memory-detail.js",
    ):
        source = _read(path)
        assert "--client-badge-bg" in source, path
        assert "--client-badge-fg" in source, path
