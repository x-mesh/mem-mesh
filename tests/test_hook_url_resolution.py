"""Tests for hook URL resolution: env > config file > baked > default."""

from pathlib import Path

import pytest

from app.cli.hooks.status import (
    _extract_url_from_script,
    _read_config_file_url,
    resolve_api_url,
)

# ---------------------------------------------------------------------------
# _extract_url_from_script
# ---------------------------------------------------------------------------


def test_extract_url_legacy_pattern(tmp_path: Path) -> None:
    script = tmp_path / "hook.sh"
    script.write_text('API_URL="${MEM_MESH_API_URL:-http://legacy.example.com}"\n')
    assert _extract_url_from_script(script) == "http://legacy.example.com"


def test_extract_url_config_file_pattern(tmp_path: Path) -> None:
    script = tmp_path / "hook.sh"
    script.write_text(
        'API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null '
        '|| echo https://baked.example.com)}"\n'
    )
    assert _extract_url_from_script(script) == "https://baked.example.com"


def test_extract_url_placeholder_pattern(tmp_path: Path) -> None:
    # installer leaves __DEFAULT_URL__ before substitution
    script = tmp_path / "hook.sh"
    script.write_text(
        'API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null '
        '|| echo __DEFAULT_URL__)}"\n'
    )
    assert _extract_url_from_script(script) == "__DEFAULT_URL__"


def test_extract_url_missing_file(tmp_path: Path) -> None:
    assert _extract_url_from_script(tmp_path / "nope.sh") is None


def test_extract_url_no_pattern(tmp_path: Path) -> None:
    script = tmp_path / "hook.sh"
    script.write_text("#!/bin/bash\necho hello\n")
    assert _extract_url_from_script(script) is None


# ---------------------------------------------------------------------------
# _read_config_file_url
# ---------------------------------------------------------------------------


def test_read_config_file_url_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".mem-mesh"
    cfg_dir.mkdir()
    (cfg_dir / "api_url").write_text("https://meme.example.online\n")
    assert _read_config_file_url() == "https://meme.example.online"


def test_read_config_file_url_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _read_config_file_url() is None


def test_read_config_file_url_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".mem-mesh"
    cfg_dir.mkdir()
    (cfg_dir / "api_url").write_text("   \n")
    assert _read_config_file_url() is None


# ---------------------------------------------------------------------------
# resolve_api_url priority chain
# ---------------------------------------------------------------------------


def _clear_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEM_MESH_API_URL", raising=False)
    monkeypatch.delenv("API_URL", raising=False)


def test_resolve_priority_env_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".mem-mesh"
    cfg.mkdir()
    (cfg / "api_url").write_text("https://file.example.com\n")
    monkeypatch.setenv("MEM_MESH_API_URL", "https://env.example.com")
    url, source = resolve_api_url(baked_url="https://baked.example.com")
    assert url == "https://env.example.com"
    assert source == "MEM_MESH_API_URL env"


def test_resolve_priority_api_url_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_url_env(monkeypatch)
    monkeypatch.setenv("API_URL", "https://api-env.example.com")
    url, source = resolve_api_url(baked_url="https://baked.example.com")
    assert url == "https://api-env.example.com"
    assert source == "API_URL env"


def test_resolve_priority_config_file_when_no_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_url_env(monkeypatch)
    cfg = tmp_path / ".mem-mesh"
    cfg.mkdir()
    (cfg / "api_url").write_text("https://file.example.com\n")
    url, source = resolve_api_url(baked_url="https://baked.example.com")
    assert url == "https://file.example.com"
    assert source == "~/.mem-mesh/api_url"


def test_resolve_priority_baked_when_no_env_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_url_env(monkeypatch)
    url, source = resolve_api_url(baked_url="https://baked.example.com")
    assert url == "https://baked.example.com"
    assert source == "installed script"


def test_resolve_priority_default_when_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_url_env(monkeypatch)
    url, source = resolve_api_url(baked_url=None)
    assert url.startswith("http://")  # DEFAULT_URL
    assert source == "default"


def test_resolve_strips_trailing_slash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_url_env(monkeypatch)
    monkeypatch.setenv("MEM_MESH_API_URL", "https://env.example.com/")
    url, _ = resolve_api_url()
    assert url == "https://env.example.com"
