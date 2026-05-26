"""Network reachability checks for Claude Code HTTP-type hooks.

Claude Code's native HTTP hooks (``"type": "http"``) refuse to call a URL whose
hostname resolves to anything other than a public address or loopback
(127.0.0.1, ::1).  Private, link-local, and CGNAT/shared addresses are blocked
as an SSRF guard.  Self-hosted mem-mesh servers reached over Tailscale/VPN/LAN
land in the CGNAT (``100.64.0.0/10``) or private ranges, so installing
http-mode hooks against such a URL produces hooks that fail at runtime with
``HTTP hook blocked: ... resolves to a private/link-local address``.

These helpers let the installer downgrade to command (``api``) hooks up front
and let ``doctor`` flag an already-broken install.
"""

import ipaddress
import socket
from typing import List, Optional
from urllib.parse import urlparse


def _resolve_addresses(host: str) -> List[str]:
    """Resolve a hostname to all of its IP addresses (IPv4 + IPv6)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def _is_allowed_ip(ip: ipaddress._BaseAddress) -> bool:
    """True when Claude Code's HTTP hook guard permits this address.

    Only loopback and globally-routable (public) addresses are allowed.
    Private (RFC 1918), link-local, and CGNAT/shared (``100.64.0.0/10``)
    addresses are rejected — note that ``is_private`` does *not* cover the
    CGNAT range, so ``is_global`` is the reliable discriminator.
    """
    return ip.is_loopback or ip.is_global


def check_http_hook_url(url: str) -> Optional[str]:
    """Return a reason string if ``url`` would be blocked by Claude Code's HTTP
    hook SSRF guard, or ``None`` when the URL is safe for an http-type hook.

    A URL is blocked when its hostname resolves to a private, link-local, or
    CGNAT/shared address.  Loopback and public addresses pass.
    """
    host = urlparse(url).hostname
    if not host:
        return f"cannot parse a host from URL: {url!r}"

    # Bare IP literal — classify directly without a DNS lookup.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_allowed_ip(literal):
            return None
        return (
            f"{host} is a private/link-local/CGNAT address — Claude Code HTTP "
            f"hooks only allow loopback (127.0.0.1, ::1) or public addresses. "
            f"Use --mode api (command hooks) for Tailscale/VPN/LAN servers."
        )

    addresses = _resolve_addresses(host)
    if not addresses:
        return f"{host} does not resolve to any IP address"

    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if not _is_allowed_ip(ip):
            return (
                f"{host} resolves to {addr} (private/link-local/CGNAT) — Claude "
                f"Code HTTP hooks only allow loopback (127.0.0.1, ::1) or public "
                f"addresses. Use --mode api (command hooks) for Tailscale/VPN/LAN "
                f"servers."
            )
    return None
