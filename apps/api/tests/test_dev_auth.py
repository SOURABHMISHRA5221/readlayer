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


def test_bypass_injects_the_dev_uid(monkeypatch):
    from app.auth import current_uid
    from app.main import app

    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    config.get_settings.cache_clear()
    seen = []

    async def spy() -> str:
        uid = await current_uid(config.get_settings())
        seen.append(uid)
        return uid

    app.dependency_overrides[current_uid] = spy
    try:
        assert TestClient(app).get("/v1/content").status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert seen == [DEV_UID]
