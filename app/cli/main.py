"""Unified CLI entry point for mem-mesh.

Usage:
    mem-mesh install          # Onboarding wizard
    mem-mesh serve            # Start API server
    mem-mesh hooks install    # Install hooks
    mem-mesh hooks status     # Hook status
    mem-mesh hooks doctor     # Hook diagnostics
    mem-mesh status           # Full system status
    mem-mesh mcp stdio        # FastMCP stdio server
    mem-mesh mcp pure         # Pure MCP stdio server
"""

import argparse
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> None:
    """Unified CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mem-mesh",
        description="mem-mesh: Centralized memory system for AI development tools.",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- mem-mesh install ---
    install_parser = sub.add_parser("install", help="Onboarding wizard (hooks + server check + MCP config)")
    install_parser.add_argument("--url", help="API server URL (default: from MEM_MESH_API_URL or http://localhost:8000)")
    install_parser.add_argument("--target", choices=["claude", "kiro", "cursor", "all", "auto"], default="auto", help="Target IDE (default: auto-detect)")
    install_parser.add_argument("--profile", choices=["standard", "enhanced", "minimal"], default="standard", help="Hook profile")
    install_parser.add_argument("-y", "--yes", action="store_true", help="Non-interactive mode (use defaults)")

    # --- mem-mesh serve ---
    serve_parser = sub.add_parser("serve", help="Start API server (dashboard + SSE + MCP)")
    serve_parser.add_argument("--host", type=str, default=None, help="Host address")
    serve_parser.add_argument("--port", type=int, default=None, help="Port number")
    serve_parser.add_argument("--workers", type=int, default=None, help="Number of workers")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    # --- mem-mesh hooks (delegate to install_hooks.py) ---
    hooks_parser = sub.add_parser("hooks", help="Hook management")
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_command", help="Hook commands")

    hooks_install = hooks_sub.add_parser("install", help="Install hooks")
    hooks_install.add_argument("--target", choices=["claude", "kiro", "cursor", "all"], default="all")
    hooks_install.add_argument("--url", default=None, help="API URL")
    hooks_install.add_argument("--mode", choices=["api", "local"], default="api")
    hooks_install.add_argument("--path", default="", help="mem-mesh path (local mode)")
    hooks_install.add_argument("--profile", choices=["standard", "enhanced", "minimal"], default="standard")
    hooks_install.add_argument("-i", "--interactive", action="store_true")

    hooks_sub.add_parser("uninstall", help="Uninstall hooks").add_argument(
        "--target", choices=["claude", "kiro", "cursor", "all"], default="all"
    )
    hooks_sub.add_parser("status", help="Show hook status")
    hooks_sub.add_parser("doctor", help="Run hook diagnostics")

    hooks_sync = hooks_sub.add_parser("sync-project", help="Sync project-local hooks")
    hooks_sync.add_argument("--target", choices=["kiro", "cursor", "all"], default="all")
    hooks_sync.add_argument("--project-id", default="mem-mesh")

    # --- mem-mesh update ---
    update_parser = sub.add_parser("update", help="Self-update mem-mesh from PyPI")
    update_parser.add_argument("--check", action="store_true", help="Check for updates only (no install)")
    update_parser.add_argument("--skip-hooks", action="store_true", help="Skip hook re-installation")
    update_parser.add_argument("--pre", action="store_true", help="Include pre-release versions")

    # --- mem-mesh config ---
    sub.add_parser("config", help="Show configuration and environment variables")

    # --- mem-mesh status ---
    sub.add_parser("status", help="Full system status (server + hooks + MCP)")

    # --- mem-mesh mcp ---
    mcp_parser = sub.add_parser("mcp", help="MCP server management")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", help="MCP commands")
    mcp_sub.add_parser("stdio", help="Start FastMCP stdio server")
    mcp_sub.add_parser("pure", help="Start Pure MCP stdio server")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    # --- Dispatch ---
    if args.command == "install":
        from app.cli.onboarding import cmd_onboarding

        cmd_onboarding(
            url=args.url,
            target=args.target,
            profile=args.profile,
            yes=args.yes,
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

    elif args.command == "config":
        from app.cli.config_cmd import cmd_config

        cmd_config()

    elif args.command == "status":
        from app.cli.system_status import cmd_system_status

        cmd_system_status()

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
        else:
            sub.choices["mcp"].print_help()


def _dispatch_hooks(args: argparse.Namespace) -> None:
    """Dispatch hooks subcommands to install_hooks module."""
    from app.cli.hooks.constants import DEFAULT_URL

    if args.hooks_command is None:
        print("Usage: mem-mesh hooks {install|uninstall|status|doctor|sync-project}")
        return

    if args.hooks_command == "install":
        if getattr(args, "interactive", False):
            from app.cli.install_hooks import cmd_interactive

            cmd_interactive()
        else:
            from app.cli.install_hooks import cmd_install

            url = args.url or DEFAULT_URL
            cmd_install(args.target, url, args.mode, args.path, args.profile)

    elif args.hooks_command == "uninstall":
        from app.cli.install_hooks import cmd_uninstall

        cmd_uninstall(args.target)

    elif args.hooks_command == "status":
        from app.cli.hooks.status import cmd_status

        cmd_status()

    elif args.hooks_command == "doctor":
        from app.cli.hooks.doctor import cmd_doctor

        cmd_doctor()

    elif args.hooks_command == "sync-project":
        from app.cli.install_hooks import cmd_sync_project

        cmd_sync_project(args.target, args.project_id)


if __name__ == "__main__":
    main()
