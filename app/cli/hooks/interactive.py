"""Compatibility wrapper for the hook installer wizard."""


def cmd_interactive() -> None:
    """Run the canonical interactive hook installer."""
    from app.cli.install_hooks import cmd_interactive as _cmd_interactive

    _cmd_interactive()
