"""Interactive hook installation wizard."""

import os
from pathlib import Path
from typing import List

from app.cli.hooks.constants import DEFAULT_URL, HOOK_PROFILES


def _prompt_choice(prompt: str, options: List[str], default: int = 0) -> int:
    """Show numbered options and return the selected index."""
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i - 1 == default else ""
        print(f"  {i}) {opt}{marker}")
    while True:
        raw = input(f"  Select [{default + 1}]: ").strip()
        if not raw:
            return default
        try:
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice - 1
        except ValueError:
            pass
        print(f"  Please enter 1-{len(options)}")
    raise RuntimeError("unreachable")


def cmd_interactive() -> None:
    """Interactive hook installation wizard."""
    print("=" * 44)
    print("  mem-mesh hooks installer (interactive)")
    print("=" * 44)
    print()

    # Step 1: target
    print("[1/4] Select target IDE:")
    targets = ["Claude Code", "Kiro", "Cursor", "All"]
    target_keys = ["claude", "kiro", "cursor", "all"]
    idx = _prompt_choice("", targets, default=3)
    target = target_keys[idx]
    print()

    # Step 2: hook profile
    print("[2/4] Select hook profile:")
    profile_options = [
        f"Standard — {HOOK_PROFILES['standard']['description']}",
        f"Enhanced — {HOOK_PROFILES['enhanced']['description']}",
        f"Minimal  — {HOOK_PROFILES['minimal']['description']}",
    ]
    profile_keys = ["standard", "enhanced", "minimal"]
    profile_idx = _prompt_choice("", profile_options, default=0)
    profile = profile_keys[profile_idx]
    print()

    if profile == "enhanced":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("  NOTE: Enhanced profile requires ANTHROPIC_API_KEY.")
            print("  The reflect hook will be inactive until the key is set.")
            print("  Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
            print()

    # Step 3: storage mode
    print("[3/4] Select storage mode:")
    modes = [
        f"API  — Send to remote server ({DEFAULT_URL})",
        "Local — Save directly to local SQLite",
    ]
    mode_idx = _prompt_choice("", modes, default=0)
    mode = "api" if mode_idx == 0 else "local"
    print()

    # Step 4: mode-specific config
    url = DEFAULT_URL
    mem_path = ""
    if mode == "api":
        print(f"[4/4] API URL [{DEFAULT_URL}]:")
        raw = input("  > ").strip()
        if raw:
            url = raw
    else:
        default_path = str(Path(__file__).resolve().parent.parent.parent.parent)
        print(f"[4/4] mem-mesh project path [{default_path}]:")
        raw = input("  > ").strip()
        mem_path = raw if raw else default_path
    print()

    from app.cli.install_hooks import cmd_install
    cmd_install(target, url, mode, mem_path, profile)
