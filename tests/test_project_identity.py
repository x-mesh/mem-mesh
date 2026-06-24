import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.cli.project_identity import GIT_CONFIG_KEY, cmd_init, resolved_project_identity

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir()
    _git(["init", "-q"], path)


def test_init_defaults_to_git_root_basename(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "MyProject"
    _init_repo(repo)
    monkeypatch.chdir(repo)

    assert cmd_init(yes=True) == 0

    assert _git(["config", "--local", "--get", GIT_CONFIG_KEY], repo) == "my-project"
    out = capsys.readouterr().out
    assert "Project ID: my-project" in out
    assert f"Stored: git config {GIT_CONFIG_KEY}" in out


def test_init_from_cwd_overrides_existing_git_config(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    nested = repo / "Feature Work"
    nested.mkdir()
    _git(["config", "--local", GIT_CONFIG_KEY, "canonical"], repo)
    monkeypatch.chdir(nested)

    assert cmd_init(yes=True, from_cwd=True) == 0

    assert _git(["config", "--local", "--get", GIT_CONFIG_KEY], repo) == "feature-work"


def test_init_uses_explicit_project_id(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)

    assert cmd_init(project_id="Explicit_Project", yes=True) == 0

    assert (
        _git(["config", "--local", "--get", GIT_CONFIG_KEY], repo) == "explicit-project"
    )


def test_init_outside_git_writes_project_file(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "Plain Project"
    project.mkdir()
    monkeypatch.chdir(project)

    assert cmd_init(yes=True) == 0

    assert (project / ".mem-mesh" / "project-id").read_text(encoding="utf-8") == (
        "plain-project\n"
    )


def test_init_show_reports_effective_resolution_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["config", "--local", GIT_CONFIG_KEY, "configured-project"], repo)
    monkeypatch.chdir(repo)

    assert cmd_init(show=True, json_mode=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "project_id": "configured-project",
        "source": "git config",
        "configured": True,
    }


def test_resolved_project_identity_prefers_env(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["config", "--local", GIT_CONFIG_KEY, "configured-project"], repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("MEM_MESH_PROJECT_ID", "Env Project")

    identity = resolved_project_identity()

    assert identity.project_id == "env-project"
    assert identity.source == "env"
