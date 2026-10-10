import importlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import config
from app.auth import DEV_UID
from app.config import Settings
from app.store.content_repo import InMemoryContentStore, set_content_store


@pytest.fixture(autouse=True)
def store():
    set_content_store(InMemoryContentStore())
    yield
    set_content_store(None)


def test_settings_refuse_bypass_on_cloud_run():
    with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS"):
        Settings(_env_file=None, dev_auth_bypass=True, k_service="readlayer-api")


@pytest.mark.parametrize("host", ["firebase_auth_emulator_host", "firestore_emulator_host"])
def test_settings_refuse_emulator_hosts_when_deployed(host):
    with pytest.raises(ValidationError, match="emulator hosts"):
        Settings(_env_file=None, k_service="readlayer-api", **{host: "127.0.0.1:9099"})
    with pytest.raises(ValidationError, match="emulator hosts"):
        Settings(_env_file=None, env="prod", **{host: "127.0.0.1:9099"})
    assert Settings(_env_file=None, **{host: "127.0.0.1:9099"})  # fine on a laptop


def test_settings_refuse_bypass_in_prod():
    with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS"):
        Settings(_env_file=None, dev_auth_bypass=True, env="prod")


def test_cloud_run_without_bypass_is_fine():
    assert Settings(_env_file=None, k_service="readlayer-api").dev_auth_bypass is False


def test_app_refuses_to_start_with_bypass_on_cloud_run(monkeypatch):
    import app.main

    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    monkeypatch.setenv("K_SERVICE", "readlayer-api")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS"):
            importlib.reload(app.main)
    finally:
        monkeypatch.delenv("DEV_AUTH_BYPASS")
        monkeypatch.delenv("K_SERVICE")
        config.get_settings.cache_clear()
        importlib.reload(app.main)


def test_read_routes_require_auth_without_bypass():
    from app.main import app

    assert TestClient(app).get("/v1/content").status_code == 401


def test_bypass_acts_as_the_dev_uid_only_without_a_token(monkeypatch, docs):
    from app.main import app

    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    config.get_settings.cache_clear()
    client = TestClient(app)
    assert client.get("/v1/content").status_code == 200
    assert f"users/{DEV_UID}" in docs.docs
    # A token, even a bad one, always goes through verification.
    bad = client.get("/v1/content", headers={"Authorization": "Bearer nonsense"})
    assert bad.status_code == 401


def test_bypass_is_rechecked_per_request(monkeypatch):
    """Even if settings were somehow built with the flag, a Cloud Run env disables it."""
    from app.main import app

    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    config.get_settings.cache_clear()
    settings = config.get_settings()
    object.__setattr__(settings, "k_service", "readlayer-api")
    assert settings.bypass_allowed is False
    assert TestClient(app).get("/v1/content").status_code == 401
