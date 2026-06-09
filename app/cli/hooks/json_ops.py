"""JSON settings merge, removal, and hook detection utilities."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


class MalformedSettingsError(RuntimeError):
    """Raised when an existing settings JSON cannot be parsed and would be
    overwritten.

    Before the error is raised the original file is preserved at
    ``<path>.bak`` so nothing is lost. Pass ``force=True`` to overwrite the
    malformed file instead of raising.
    """


def _atomic_write_text(path: Path, text: str, *, mode: Optional[int] = None) -> None:
    """Write ``text`` to ``path`` atomically.

    The content is written to a temporary file in the same directory and then
    swapped into place with :func:`os.replace`, so a crash mid-write can never
    truncate or corrupt the original file. ``mode`` (e.g. ``0o600``) is applied
    to the temp file before the swap to avoid a permissions race.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_settings_or_raise(path: Path, *, force: bool = False) -> Dict[str, Any]:
    """Load a JSON settings object, tolerating a missing file.

    A missing file yields ``{}``. A file that is not valid JSON (or not a JSON
    object) is first backed up to ``<path>.bak``; then, unless ``force`` is set,
    :class:`MalformedSettingsError` is raised so the caller does not silently
    overwrite user data. With ``force=True`` an empty dict is returned and the
    caller may overwrite (the backup is still made).
    """
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
        parse_ok = isinstance(data, dict)
    except json.JSONDecodeError:
        data = None
        parse_ok = False

    if parse_ok:
        return data

    backup: Optional[Path] = path.with_suffix(path.suffix + ".bak")
    try:
        shutil.copy2(path, backup)
    except OSError:
        backup = None
    if not force:
        raise MalformedSettingsError(
            f"Existing settings at {path} is not valid JSON. "
            + (f"Original backed up to {backup}. " if backup else "")
            + "Re-run with --force to overwrite."
        )
    return {}


def _is_mem_mesh_hook(hook: Dict[str, Any]) -> bool:
    """Return True if a hook definition belongs to mem-mesh."""
    hook_type = str(hook.get("type", ""))
    command = str(hook.get("command", ""))
    prompt = str(hook.get("prompt", ""))
    url = str(hook.get("url", ""))
    if "mem-mesh-" in command:
        return True
    # http mode: native HTTP hooks point at the mem-mesh hook endpoints.
    if hook_type == "http" and "/api/hooks/claude/" in url:
        return True
    if hook_type == "prompt" and "mcp__mem-mesh__add" in prompt:
        return True
    return False


def _is_mem_mesh_entry(entry: Dict[str, Any]) -> bool:
    """Return True if a hook entry contains mem-mesh managed hooks."""
    if _is_mem_mesh_hook(entry):
        return True
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(isinstance(hook, dict) and _is_mem_mesh_hook(hook) for hook in hooks)


def _merge_hook_entries(
    existing_entries: List[Dict[str, Any]],
    patch_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge event entries while preserving non mem-mesh user hooks."""
    preserved = [
        entry
        for entry in existing_entries
        if isinstance(entry, dict) and not _is_mem_mesh_entry(entry)
    ]
    passthrough = [
        entry
        for entry in patch_entries
        if isinstance(entry, dict) and not _is_mem_mesh_entry(entry)
    ]
    managed = [
        entry
        for entry in patch_entries
        if isinstance(entry, dict) and _is_mem_mesh_entry(entry)
    ]
    return preserved + passthrough + managed


def _merge_json_settings(
    path: Path, patch: Dict[str, Any], *, force: bool = False
) -> None:
    """Merge patch into an existing JSON file, preserving other keys.

    If the existing file is malformed it is backed up to ``<path>.bak`` and
    :class:`MalformedSettingsError` is raised (unless ``force=True``), instead
    of silently discarding the user's settings. The write itself is atomic.
    """
    existing: Dict[str, Any] = _load_settings_or_raise(path, force=force)

    # Deep-merge hooks section only; preserve everything else.
    # For each hook event, keep existing non mem-mesh entries and upsert only
    # mem-mesh-managed entries from patch.
    for key, value in patch.items():
        if key == "hooks" and key in existing and isinstance(existing[key], dict):
            existing_hooks = existing[key]
            patch_hooks = value if isinstance(value, dict) else {}
            merged_hooks = dict(existing_hooks)
            for event_name, patch_entries in patch_hooks.items():
                current_entries = existing_hooks.get(event_name, [])
                if isinstance(current_entries, list) and isinstance(
                    patch_entries, list
                ):
                    merged_hooks[event_name] = _merge_hook_entries(
                        current_entries, patch_entries
                    )
                else:
                    merged_hooks[event_name] = patch_entries
            existing[key] = merged_hooks
        else:
            existing[key] = value

    _atomic_write_text(
        path,
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def _remove_json_key(path: Path, key: str) -> None:
    """Remove a top-level key from a JSON file."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if key in data:
        del data[key]
        _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _remove_hook_event(path: Path, event_name: str) -> None:
    """Remove a specific hook event from the hooks section of a JSON file."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    hooks = data.get("hooks", {})
    if event_name in hooks:
        del hooks[event_name]
        _atomic_write_text(
            path,
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )


def _remove_mem_mesh_hooks_from_json(path: Path) -> None:
    """Remove mem-mesh hook entries from hooks.json, preserving user entries."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return

    changed = False
    for event_name, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        filtered = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and _is_mem_mesh_entry(entry))
        ]
        if len(filtered) != len(entries):
            hooks[event_name] = filtered
            changed = True
        if not hooks[event_name]:
            del hooks[event_name]
            changed = True

    if changed:
        if not hooks:
            data.pop("hooks", None)
        _atomic_write_text(
            path,
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )


def _count_mem_mesh_hook_entries(path: Path) -> int:
    """Count mem-mesh hook entries in hooks.json."""
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return 0

    count = 0
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and _is_mem_mesh_entry(entry):
                count += 1
    return count


def _remove_kiro_mem_mesh_hooks(path: Path) -> None:
    """Remove mem-mesh entries from Kiro hooks.json, preserving others."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    hooks: List[Dict[str, Any]] = data.get("hooks", [])
    data["hooks"] = [h for h in hooks if not h.get("name", "").startswith("mem-mesh:")]
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
