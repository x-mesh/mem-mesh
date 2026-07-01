"""Unified LLM resolution for relay/reconcile services.

chat_llm_* is the shared default LLM. relay and reconcile reuse it unless they
opt into their own key. The rule is deliberately predictable:

  1. If an explicit ``<service>.use_own_llm`` toggle is set (DB app_config or the
     env-backed Settings field), it wins.
  2. Otherwise a service uses its OWN key only when that key is actually
     configured; if not, it falls back to the shared chat LLM.

So "no config" always means "use the shared chat LLM", and setting a service's
own key (or flipping the toggle) is what opts it out — nothing changes silently.

Precedence for each value: DB app_config (``<ns>.llm_<field>``) > env-backed
Settings field (``<ns>_llm_<field>``) > default.
"""

from typing import Any

# Services that can reuse the shared chat LLM or bring their own.
_OWNABLE = ("relay", "reconcile")
_TRUE = ("true", "1", "yes", "on")


async def _cfg(db: Any, settings: Any, namespace: str, field: str) -> str:
    """DB app_config > env-backed Settings field, for ``<ns>.llm_<field>``."""
    db_value = await db.get_app_config(f"{namespace}.llm_{field}")
    if db_value is not None and str(db_value).strip():
        return str(db_value).strip()
    return str(getattr(settings, f"{namespace}_llm_{field}", "") or "").strip()


async def _resolve_use_own(db: Any, settings: Any, service: str, own_key: str) -> bool:
    """Decide whether ``service`` uses its own LLM (see module docstring rule)."""
    toggle = await db.get_app_config(f"{service}.use_own_llm")
    if toggle is not None:
        return str(toggle).strip().lower() in _TRUE
    if bool(getattr(settings, f"{service}_use_own_llm", False)):
        return True
    # Implicit: own key configured → use own; else fall back to shared chat.
    return bool(own_key)


async def resolve_service_llm(db: Any, settings: Any, service: str) -> dict:
    """Resolve the effective LLM config for ``service`` ('relay' | 'reconcile').

    Returns a dict with provider/api_key/model/base_url plus ``use_own`` (bool)
    and ``source`` (the namespace actually used: the service name or 'chat').
    """
    if service not in _OWNABLE:
        raise ValueError(f"resolve_service_llm: unknown service {service!r}")

    own_key = await _cfg(db, settings, service, "api_key")
    use_own = await _resolve_use_own(db, settings, service, own_key)
    ns = service if use_own else "chat"

    return {
        "provider": (await _cfg(db, settings, ns, "provider")) or "anthropic",
        "api_key": await _cfg(db, settings, ns, "api_key"),
        "model": await _cfg(db, settings, ns, "model"),
        "base_url": await _cfg(db, settings, ns, "base_url"),
        "use_own": use_own,
        "source": ns,
    }
