"""Unified CLI entry point for mem-mesh.

Usage:
    mem-mesh                  # Onboarding wizard (bare = `mem-mesh install`)
    mem-mesh --json           # Onboarding, machine-readable JSON (for agents)
    mem-mesh init             # Initialize stable project identity
    mem-mesh install          # Onboarding wizard
    mem-mesh serve            # Start API server
    mem-mesh hooks install    # Install hooks
    mem-mesh hooks status     # Hook status
    mem-mesh hooks doctor     # Hook diagnostics
    mem-mesh hooks rules      # Print hook rules
    mem-mesh status           # Full system status
    mem-mesh mcp stdio        # FastMCP stdio server
    mem-mesh mcp pure         # Pure MCP stdio server
    mem-mesh mcp config       # Configure MCP for dev tools
"""

import argparse
import sys
from typing import List, Optional

from app.core.version import __VERSION__


def main(argv: Optional[List[str]] = None) -> None:
    """Unified CLI entry point."""
    # Shared flags usable both bare (`mem-mesh --json`) and on the install
    # subcommand (`mem-mesh install --json`). The mixed order
    # `mem-mesh --json install` is NOT guaranteed (the subparser resets the
    # shared default) — use one of the two documented forms.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON, run non-interactively (implies --yes)",
    )

    parser = argparse.ArgumentParser(
        prog="mem-mesh",
        description="mem-mesh: Centralized memory system for AI development tools.",
        parents=[common],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mem-mesh {__VERSION__}",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- mem-mesh init ---
    init_parser = sub.add_parser(
        "init",
        parents=[common],
        help="Initialize stable project identity for hooks and MCP",
    )
    init_parser.add_argument(
        "--project-id",
        default=None,
        help="Canonical project id to store (default: prompt or inferred repo name)",
    )
    init_parser.add_argument(
        "--from-cwd",
        action="store_true",
        help="Use the current directory basename instead of the git root basename",
    )
    init_parser.add_argument(
        "--show",
        action="store_true",
        help="Show the currently resolved project id without changing config",
    )
    init_parser.add_argument(
        "-y", "--yes", action="store_true", help="Non-interactive mode (use defaults)"
    )

    # --- mem-mesh install ---
    install_parser = sub.add_parser(
        "install",
        parents=[common],
        help="Onboarding wizard (hooks + server check + MCP config)",
    )
    install_parser.add_argument(
        "--url",
        help="API server URL (default: from MEM_MESH_API_URL or http://localhost:8000)",
    )
    install_parser.add_argument(
        "--target",
        choices=["claude", "kiro", "cursor", "codex", "all", "auto"],
        default="auto",
        help="Target IDE (default: auto-detect)",
    )
    install_parser.add_argument(
        "--profile",
        choices=["standard", "enhanced", "minimal"],
        default="standard",
        help="Hook profile",
    )
    install_parser.add_argument(
        "-y", "--yes", action="store_true", help="Non-interactive mode (use defaults)"
    )
    install_parser.add_argument(
        "--force", action="store_true", help="Continue despite errors"
    )

    # --- mem-mesh serve ---
    serve_parser = sub.add_parser(
        "serve", help="Start API server (dashboard + SSE + MCP)"
    )
    serve_parser.add_argument("--host", type=str, default=None, help="Host address")
    serve_parser.add_argument("--port", type=int, default=None, help="Port number")
    serve_parser.add_argument(
        "--workers", type=int, default=None, help="Number of workers"
    )
    serve_parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload"
    )

    # --- mem-mesh relay ---
    relay_parser = sub.add_parser("relay", help="Relay layer utilities")
    relay_sub = relay_parser.add_subparsers(dest="relay_command", help="Relay commands")
    relay_worker = relay_sub.add_parser("worker", help="Run relay background worker")
    relay_worker.add_argument(
        "--once",
        action="store_true",
        help="Process at most one job per enabled queue and exit",
    )
    relay_worker.add_argument(
        "--tasks",
        default="outbox,item,aggregate",
        help="Comma-separated relay tasks: outbox,item,aggregate",
    )
    relay_worker.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Idle polling interval in seconds for continuous mode",
    )
    relay_worker.add_argument("--worker-id", default=None, help="Stable worker id")
    relay_worker.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Retry attempts before moving a relay job to dead_letter",
    )
    relay_worker.add_argument(
        "--backoff-max",
        type=float,
        default=300.0,
        help="Maximum retry backoff in seconds",
    )
    relay_worker.add_argument(
        "--lease-seconds",
        type=int,
        default=300,
        help="Seconds before a processing relay job can be reclaimed",
    )
    relay_worker.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of relay worker loops to run in this process",
    )
    relay_worker.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    relay_worker.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Include relay queue diagnostics in the worker result",
    )
    relay_materialize = relay_sub.add_parser(
        "materialize",
        help="Backfill received relay rows into ordinary memories",
    )
    relay_materialize.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum relay current rows to scan",
    )
    relay_materialize.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )

    # --- mem-mesh hooks (delegate to install_hooks.py) ---
    hooks_parser = sub.add_parser("hooks", help="Hook management")
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_command", help="Hook commands")

    hooks_install = hooks_sub.add_parser("install", help="Install hooks")
    hooks_install.add_argument(
        "--target", choices=["claude", "kiro", "cursor", "codex", "all"], default="all"
    )
    hooks_install.add_argument("--url", default=None, help="API URL")
    hooks_install.add_argument(
        "--mode", choices=["api", "local", "http"], default="api"
    )
    hooks_install.add_argument("--path", default="", help="mem-mesh path (local mode)")
    hooks_install.add_argument(
        "--profile", choices=["standard", "enhanced", "minimal"], default="standard"
    )
    hooks_install.add_argument(
        "--scope",
        choices=["global", "project"],
        default="global",
        help="Install globally or under a project directory",
    )
    hooks_install.add_argument(
        "--dir",
        default="",
        help="Project directory for --scope project (default: current directory)",
    )
    hooks_install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite malformed hook settings after backing them up",
    )
    hooks_install.add_argument("-i", "--interactive", action="store_true")

    hooks_sub.add_parser("uninstall", help="Uninstall hooks").add_argument(
        "--target", choices=["claude", "kiro", "cursor", "codex", "all"], default="all"
    )
    hooks_sub.add_parser("status", help="Show hook status")
    hooks_sub.add_parser("doctor", help="Run hook diagnostics")
    hooks_rules = hooks_sub.add_parser(
        "rules", help="Print hook rules to stdout for copy/paste"
    )
    hooks_rules.add_argument(
        "--project-id",
        default="mem-mesh",
        help="Project ID to embed in the rendered rules",
    )
    hooks_rules.add_argument(
        "--format",
        choices=["plain", "claude"],
        default="plain",
        help="Output format: plain rules or a CLAUDE.md managed block",
    )

    hooks_sync = hooks_sub.add_parser("sync-project", help="Sync project-local hooks")
    hooks_sync.add_argument(
        "--target", choices=["claude", "kiro", "cursor", "all"], default="all"
    )
    hooks_sync.add_argument("--project-id", default="mem-mesh")

    # --- mem-mesh update ---
    update_parser = sub.add_parser("update", help="Self-update mem-mesh from PyPI")
    update_parser.add_argument(
        "--check", action="store_true", help="Check for updates only (no install)"
    )
    update_parser.add_argument(
        "--skip-hooks", action="store_true", help="Skip hook re-installation"
    )
    update_parser.add_argument(
        "--pre", action="store_true", help="Include pre-release versions"
    )

    # --- mem-mesh config ---
    config_parser = sub.add_parser(
        "config", help="Show configuration and environment variables"
    )
    config_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show installed MCP config JSON with line numbers + syntax highlighting",
    )

    # --- mem-mesh status ---
    status_parser = sub.add_parser(
        "status", help="Full system status (server + hooks + MCP)"
    )
    status_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show installed MCP config JSON with line numbers + syntax highlighting",
    )

    # --- mem-mesh doctor (top-level full diagnostics) ---
    doctor_parser = sub.add_parser(
        "doctor", help="Full diagnostics: API + MCP + token + hooks, with fixes"
    )
    doctor_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show installed config JSON"
    )

    # --- mem-mesh restore (recover a config from a timestamped backup) ---
    restore_parser = sub.add_parser(
        "restore", help="Restore an MCP / hooks config file from a backup"
    )
    restore_parser.add_argument(
        "--list", dest="list_only", action="store_true", help="List backups and exit"
    )
    restore_parser.add_argument(
        "--from",
        dest="from_backup",
        default=None,
        help="Restore a specific backup file",
    )
    restore_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the overwrite confirmation"
    )

    # --- mem-mesh mcp ---
    mcp_parser = sub.add_parser("mcp", help="MCP server management")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", help="MCP commands")
    mcp_sub.add_parser("stdio", help="Start FastMCP stdio server")
    mcp_sub.add_parser("pure", help="Start Pure MCP stdio server")
    mcp_config_parser = mcp_sub.add_parser(
        "config", help="Configure MCP for dev tools (Codex, Cursor, Kiro, etc.)"
    )
    mcp_config_parser.add_argument("--url", default=None, help="API server URL")
    mcp_config_parser.add_argument(
        "--token",
        default=None,
        help="Hook auth token — materialize to ~/.mem-mesh/hook_token and bake it "
        "as a literal Bearer token into each tool's MCP config",
    )
    mcp_config_parser.add_argument(
        "-y", "--yes", action="store_true", help="Non-interactive mode"
    )
    mcp_config_parser.add_argument(
        "--auth",
        action="store_true",
        help="Bake an Authorization: Bearer <token> header with the literal token "
        "from the env-first effective hook token (http mode, for auth-enforcing servers)",
    )
    mcp_verify_parser = mcp_sub.add_parser(
        "verify", help="Verify mem-mesh MCP config across all detected dev tools"
    )
    mcp_verify_parser.add_argument("--url", default=None, help="API server URL")
    mcp_verify_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show each tool's config JSON"
    )
    mcp_clean_parser = mcp_sub.add_parser(
        "clean", help="Remove project-scoped MCP overrides that shadow the global entry"
    )
    mcp_clean_parser.add_argument(
        "--list", dest="list_only", action="store_true", help="List overrides and exit"
    )
    mcp_clean_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed, change nothing",
    )
    mcp_clean_parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation"
    )

    args = parser.parse_args(argv)

    # Version banner on every run — emitted to stderr so it never pollutes
    # stdout (JSON output, piped rules, the MCP stdio protocol). Skipped for
    # --json (machine-readable) and the `mcp` stdio servers.
    if not getattr(args, "json", False) and args.command != "mcp":
        from app.cli.prompts.behaviors import PROMPT_VERSION

        print(
            f"mem-mesh {__VERSION__} (prompt v{PROMPT_VERSION})",
            file=sys.stderr,
        )

    # Bare `mem-mesh` (no subcommand) runs onboarding — the simple entry point
    # for `uvx mem-mesh`. Interactive on a TTY; auto non-interactive when piped
    # or run by an agent (no stdin/stdout TTY) so prompts never hang.
    # `mem-mesh --help` is consumed by argparse before this, so help still works.
    if args.command is None:
        from app.cli.onboarding import cmd_onboarding

        json_mode = getattr(args, "json", False)
        interactive = sys.stdin.isatty() and sys.stdout.isatty() and not json_mode
        cmd_onboarding(
            url=None,
            target="auto",
            profile="standard",
            yes=not interactive,
            force=False,
            json_mode=json_mode,
        )
        return

    # --- Dispatch ---
    if args.command == "init":
        from app.cli.project_identity import cmd_init

        sys.exit(
            cmd_init(
                project_id=args.project_id,
                yes=args.yes,
                from_cwd=args.from_cwd,
                show=args.show,
                json_mode=getattr(args, "json", False),
            )
        )

    elif args.command == "install":
        from app.cli.onboarding import cmd_onboarding

        cmd_onboarding(
            url=args.url,
            target=args.target,
            profile=args.profile,
            yes=args.yes or args.json,
            force=args.force,
            json_mode=args.json,
        )

    elif args.command == "serve":
        try:
            from app.web.__main__ import main as web_main
        except ImportError:
            print("Server dependencies not installed.")
            print("Install with: pip install mem-mesh[server]")
            sys.exit(1)

        # Build argv for the web server
        web_argv: List[str] = []
        if args.host:
            web_argv.extend(["--host", args.host])
        if args.port:
            web_argv.extend(["--port", str(args.port)])
        if args.workers:
            web_argv.extend(["--workers", str(args.workers)])
        if args.reload:
            web_argv.append("--reload")
        # Override sys.argv for web main
        sys.argv = ["mem-mesh-web"] + web_argv
        web_main()

    elif args.command == "update":
        from app.cli.updater import cmd_update

        cmd_update(
            skip_hooks=args.skip_hooks,
            check_only=args.check,
            pre=args.pre,
        )

    elif args.command == "hooks":
        _dispatch_hooks(args)

    elif args.command == "relay":
        if args.relay_command == "worker":
            from app.cli.relay import cmd_relay_worker

            sys.exit(
                cmd_relay_worker(
                    once=args.once,
                    json_mode=args.json,
                    tasks=args.tasks,
                    interval=args.interval,
                    worker_id=args.worker_id,
                    max_attempts=args.max_attempts,
                    backoff_max=args.backoff_max,
                    lease_seconds=args.lease_seconds,
                    concurrency=args.concurrency,
                    verbose=args.verbose,
                )
            )
        elif args.relay_command == "materialize":
            from app.cli.relay import cmd_relay_materialize

            sys.exit(
                cmd_relay_materialize(
                    limit=args.limit,
                    json_mode=args.json,
                )
            )
        else:
            sub.choices["relay"].print_help()

    elif args.command == "config":
        from app.cli.config_cmd import cmd_config

        cmd_config(verbose=args.verbose)

    elif args.command == "status":
        from app.cli.system_status import cmd_system_status

        cmd_system_status(verbose=args.verbose)

    elif args.command == "doctor":
        from app.cli.system_doctor import cmd_system_doctor

        sys.exit(cmd_system_doctor(verbose=args.verbose))

    elif args.command == "restore":
        from app.cli.restore import cmd_restore

        sys.exit(
            cmd_restore(
                list_only=args.list_only,
                from_backup=args.from_backup,
                yes=args.yes,
            )
        )

    elif args.command == "mcp":
        if args.mcp_command == "stdio":
            try:
                from app.mcp_stdio.__main__ import main as mcp_stdio_main
            except ImportError:
                print("Server dependencies not installed.")
                print("Install with: pip install mem-mesh[server]")
                sys.exit(1)
            mcp_stdio_main()
        elif args.mcp_command == "pure":
            try:
                from app.mcp_stdio_pure.__main__ import main as mcp_pure_main
            except ImportError:
                print("Server dependencies not installed.")
                print("Install with: pip install mem-mesh[server]")
                sys.exit(1)
            mcp_pure_main()
        elif args.mcp_command == "config":
            from app.cli.hooks.status import resolve_api_url
            from app.cli.mcp_config import run_mcp_setup

            # Explicit --url wins; otherwise resolve via env > ~/.mem-mesh/api_url
            # > default. (run_mcp_setup no longer re-applies the env override, so
            # an explicit --url is honored instead of being silently shadowed.)
            url = args.url or resolve_api_url()[0]
            with_auth = args.auth
            if args.url:
                # Align the hook channel too: materialize the URL so hooks and MCP
                # point at the same server. Without this, `mcp config --url` only
                # moves MCP and leaves hooks on whatever the env/file said.
                from app.cli.install_hooks import API_URL_FILE, _ensure_api_url

                _ensure_api_url(args.url)
                print(f"  API URL written to {API_URL_FILE} (materialized hook config)")
            explicit_token = None
            if args.token:
                from app.cli.install_hooks import HOOK_TOKEN_FILE, _write_hook_token

                _write_hook_token(args.token)
                with_auth = True  # a supplied token implies authenticated MCP
                explicit_token = args.token
                print(f"  Hook token written to {HOOK_TOKEN_FILE}")
            run_mcp_setup(
                url=url, yes=args.yes, with_auth=with_auth, token=explicit_token
            )
        elif args.mcp_command == "verify":
            from app.cli.hooks.status import resolve_api_url
            from app.cli.mcp_verify import cmd_mcp_verify

            url = args.url or resolve_api_url()[0]
            sys.exit(cmd_mcp_verify(url=url, verbose=args.verbose))
        elif args.mcp_command == "clean":
            from app.cli.mcp_clean import cmd_mcp_clean

            sys.exit(
                cmd_mcp_clean(
                    list_only=args.list_only, yes=args.yes, dry_run=args.dry_run
                )
            )
        else:
            sub.choices["mcp"].print_help()


def _dispatch_hooks(args: argparse.Namespace) -> None:
    """Dispatch hooks subcommands to install_hooks module."""
    from app.cli.hooks.constants import DEFAULT_URL

    if args.hooks_command is None:
        print(
            "Usage: mem-mesh hooks "
            "{install|uninstall|status|doctor|rules|sync-project}"
        )
        return

    if args.hooks_command == "install":
        if getattr(args, "interactive", False):
            from app.cli.install_hooks import cmd_interactive

            cmd_interactive()
        else:
            from app.cli.install_hooks import cmd_install

            url = args.url or DEFAULT_URL
            cmd_install(
                args.target,
                url,
                args.mode,
                args.path,
                args.profile,
                force=args.force,
                scope=args.scope,
                dir_path=args.dir,
            )

    elif args.hooks_command == "uninstall":
        from app.cli.install_hooks import cmd_uninstall

        cmd_uninstall(args.target)

    elif args.hooks_command == "status":
        from app.cli.hooks.status import cmd_status

        cmd_status()

    elif args.hooks_command == "doctor":
        from app.cli.hooks.doctor import cmd_doctor

        cmd_doctor()

    elif args.hooks_command == "rules":
        from app.cli.install_hooks import cmd_rules

        cmd_rules(args.project_id, args.format)

    elif args.hooks_command == "sync-project":
        from app.cli.install_hooks import cmd_sync_project

        cmd_sync_project(args.target, args.project_id)


if __name__ == "__main__":
    main()
