"""WS2 (R9): relay 세션 digest 설정 3키 — 기본값·env 오버라이드·검증."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_session_digest_defaults():
    s = Settings(_env_file=None)
    assert s.relay_federated_session_digest_enabled is True
    assert s.relay_federated_session_digest_refresh_minutes == 15
    assert s.relay_federated_session_digest_max_age_minutes == 60


def test_session_digest_env_override(monkeypatch):
    monkeypatch.setenv("MEM_MESH_RELAY_FEDERATED_SESSION_DIGEST_ENABLED", "false")
    monkeypatch.setenv("MEM_MESH_RELAY_FEDERATED_SESSION_DIGEST_REFRESH_MINUTES", "5")
    monkeypatch.setenv("MEM_MESH_RELAY_FEDERATED_SESSION_DIGEST_MAX_AGE_MINUTES", "120")
    s = Settings(_env_file=None)
    assert s.relay_federated_session_digest_enabled is False
    assert s.relay_federated_session_digest_refresh_minutes == 5
    assert s.relay_federated_session_digest_max_age_minutes == 120


@pytest.mark.parametrize("field", ["refresh_minutes", "max_age_minutes"])
def test_session_digest_minutes_must_be_ge_1(monkeypatch, field):
    monkeypatch.setenv(f"MEM_MESH_RELAY_FEDERATED_SESSION_DIGEST_{field.upper()}", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
