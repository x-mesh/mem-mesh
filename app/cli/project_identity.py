"""Project identity initialization and hook-side resolution helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.schemas.requests import normalize_project_id

GIT_CONFIG_KEY = "mem-mesh.project-id"
ENV_PROJECT_ID = "MEM_MESH_PROJECT_ID"
PROJECT_ID_FILE = Path(".mem-mesh") / "project-id"


SHELL_PROJECT_ID_RESOLVER = r"""# --- mem-mesh project id resolution ------------------------------------------
mem_mesh_project_id() {
  if [ -n "${MEM_MESH_PROJECT_ID:-}" ]; then
    printf '%s\n' "$MEM_MESH_PROJECT_ID"
    return 0
  fi

  _mm_pid="$(git config --local --get mem-mesh.project-id 2>/dev/null || true)"
  if [ -n "$_mm_pid" ]; then
    printf '%s\n' "$_mm_pid"
    return 0
  fi

  _mm_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  _mm_file="${_mm_root}/.mem-mesh/project-id"
  if [ -f "$_mm_file" ]; then
    _mm_pid="$(sed -n '1{s/[[:space:]]*$//;p;}' "$_mm_file" 2>/dev/null || true)"
    if [ -n "$_mm_pid" ]; then
      printf '%s\n' "$_mm_pid"
      return 0
    fi
  fi

  _mm_base="$(basename "$_mm_root" 2>/dev/null || true)"
  if [ -n "$_mm_base" ]; then
    printf '%s\n' "$_mm_base"
  else
    printf '%s\n' "unknown"
  fi
}
"""


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str
    source: str


@dataclass(frozen=True)
class InitResult:
    project_id: str
    stored: str
    source: str


def _run_git(args: list[str], cwd: Optional[Path] = None) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _normalize_candidate(value: str) -> str:
    normalized = normalize_project_id(value, strict=True)
    if not normalized:
        raise ValueError("project_id must be a non-empty string")
    return normalized


def _git_root() -> Optional[Path]:
    root = _run_git(["rev-parse", "--show-toplevel"])
    return Path(root).resolve() if root else None


def _existing_git_project_id() -> Optional[str]:
    value = _run_git(["config", "--local", "--get", GIT_CONFIG_KEY])
    return value or None


def _project_file_path(root: Optional[Path] = None) -> Path:
    base = root or Path.cwd()
    return base / PROJECT_ID_FILE


def _existing_file_project_id(root: Optional[Path] = None) -> Optional[str]:
    path = _project_file_path(root)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def default_project_identity(*, from_cwd: bool = False) -> ProjectIdentity:
    """Return the default project id candidate without writing it."""
    if not from_cwd:
        env_value = (os.environ.get(ENV_PROJECT_ID) or "").strip()
        if env_value:
            return ProjectIdentity(_normalize_candidate(env_value), "env")

        existing = _existing_git_project_id()
        if existing:
            return ProjectIdentity(_normalize_candidate(existing), "git config")

    root = _git_root()
    if not from_cwd:
        existing_file = _existing_file_project_id(root)
        if existing_file:
            return ProjectIdentity(_normalize_candidate(existing_file), "project file")

    base = Path.cwd().name if from_cwd else (root.name if root else Path.cwd().name)
    return ProjectIdentity(
        _normalize_candidate(base), "cwd" if from_cwd else "git root"
    )


def resolved_project_identity() -> ProjectIdentity:
    """Return the effective runtime resolution used by hooks, as Python sees it."""
    env_value = (os.environ.get(ENV_PROJECT_ID) or "").strip()
    if env_value:
        return ProjectIdentity(_normalize_candidate(env_value), "env")

    existing = _existing_git_project_id()
    if existing:
        return ProjectIdentity(_normalize_candidate(existing), "git config")

    root = _git_root()
    existing_file = _existing_file_project_id(root)
    if existing_file:
        return ProjectIdentity(_normalize_candidate(existing_file), "project file")

    base = root.name if root else Path.cwd().name
    return ProjectIdentity(_normalize_candidate(base), "fallback")


def _write_project_file(project_id: str, root: Optional[Path]) -> Path:
    path = _project_file_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(project_id + "\n", encoding="utf-8")
    return path


def store_project_identity(project_id: str) -> InitResult:
    normalized = _normalize_candidate(project_id)
    root = _git_root()
    if root:
        result = subprocess.run(
            ["git", "config", "--local", GIT_CONFIG_KEY, normalized],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return InitResult(normalized, f"git config {GIT_CONFIG_KEY}", "git config")
        # Fall through to a project file if local git config is unavailable.

    path = _write_project_file(normalized, root)
    return InitResult(normalized, str(path), "project file")


def cmd_init(
    *,
    project_id: Optional[str] = None,
    yes: bool = False,
    from_cwd: bool = False,
    show: bool = False,
    json_mode: bool = False,
) -> int:
    """Initialize or inspect the current project's stable mem-mesh identity."""
    try:
        if show:
            identity = resolved_project_identity()
            payload = {
                "project_id": identity.project_id,
                "source": identity.source,
                "configured": identity.source in {"env", "git config", "project file"},
            }
            if json_mode:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print(f"Project ID: {identity.project_id}")
                print(f"Source: {identity.source}")
            return 0

        default = default_project_identity(from_cwd=from_cwd)
        candidate = project_id.strip() if project_id else ""
        if not candidate:
            interactive = sys.stdin.isatty() and sys.stdout.isatty() and not yes
            if interactive:
                entered = input(f"Project ID [{default.project_id}]: ").strip()
                candidate = entered or default.project_id
            else:
                candidate = default.project_id

        result = store_project_identity(candidate)
    except ValueError as exc:
        if json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    payload = {
        "ok": True,
        "project_id": result.project_id,
        "stored": result.stored,
        "source": result.source,
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"Project ID: {result.project_id}")
        print(f"Stored: {result.stored}")
    return 0
