"""Test isolation: no developer .env, no inherited cloud config, no real network.

LiteLLM loads `.env` into os.environ on import unless LITELLM_MODE is set, and Settings reads
`.env` from the working directory, so a developer's real model ids would otherwise reach tests.
"""

import os

os.environ["LITELLM_MODE"] = "PRODUCTION"  # before anything imports litellm

import socket  # noqa: E402

import pytest  # noqa: E402
from tenacity import wait_none  # noqa: E402

from app import auth, config, llm, ratelimit  # noqa: E402
from app.config import Settings  # noqa: E402
from app.store import docstore  # noqa: E402
from app.store.docstore import InMemoryDocStore  # noqa: E402
from app.store.spend_repo import InMemorySpendStore  # noqa: E402
from tests.fakes import FakeAuthAdmin  # noqa: E402

Settings.model_config["env_file"] = None

# Settings fields, plus credentials Google SDKs pick up on their own.
# The emulator hosts stay: `make test-emulator` sets them for the emulator-marked tests.
_KEEP = {"FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST"}
_SCRUB = [name.upper() for name in Settings.model_fields if name.upper() not in _KEEP] + [
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUDSDK_CONFIG",
    "VERTEXAI_PROJECT",
    "VERTEXAI_LOCATION",
]
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class NetworkBlocked(RuntimeError):
    pass


def _is_local(address: object) -> bool:
    return isinstance(address, str) or (
        isinstance(address, tuple) and bool(address) and address[0] in _LOCAL_HOSTS
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    for name in _SCRUB:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    config.get_settings.cache_clear()

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guard(address: object) -> None:
        if not _is_local(address):
            raise NetworkBlocked(f"tests must not use the network: connect to {address!r}")

    def connect(self, address):
        guard(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        guard(address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in _LOCAL_HOSTS and host is not None:
            raise NetworkBlocked(f"tests must not use the network: resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def docs() -> InMemoryDocStore:
    """Per-user state in memory and a fake Firebase token verifier for every test."""
    store = InMemoryDocStore()
    docstore.set_doc_store(store)
    auth.set_auth_admin(FakeAuthAdmin())
    ratelimit.reset()
    yield store
    docstore.set_doc_store(None)
    auth.set_auth_admin(None)
    ratelimit.reset()


@pytest.fixture
def auth_admin() -> FakeAuthAdmin:
    admin = auth.get_auth_admin()
    assert isinstance(admin, FakeAuthAdmin)
    return admin


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        gcp_project="test-project",
        model_fast="vertex_ai/fast",
        model_quality="vertex_ai/quality",
        model_fallback="vertex_ai/fallback",
        llm_daily_budget_usd=1.0,
        uid_hash_salt="test-salt",
    )


@pytest.fixture
def spend(monkeypatch: pytest.MonkeyPatch) -> InMemorySpendStore:
    store = InMemorySpendStore()
    monkeypatch.setattr(llm, "retry_wait", wait_none())
    llm.set_spend_store(store)
    yield store
    llm.set_spend_store(None)
