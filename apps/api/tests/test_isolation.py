import socket

import pytest

from app import config
from tests.conftest import NetworkBlocked


def test_guard_blocks_real_network():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443), timeout=1)


def test_no_developer_env_leaks():
    s = config.get_settings()
    assert s.model_embed == "" and s.model_fast == "" and s.gcp_project == "test-project"


async def test_contended_transactions_are_retried_then_succeed(monkeypatch):
    import asyncio as _asyncio

    from app.store import docstore

    async def no_sleep(_):
        return None

    monkeypatch.setattr(_asyncio, "sleep", no_sleep)
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("Failed to commit transaction in 5 attempts.")
        return "ok"

    assert await docstore.retry_contention(flaky) == "ok" and len(calls) == 3

    async def broken():
        raise ValueError("something else")

    import pytest as _pytest

    with _pytest.raises(ValueError, match="something else"):
        await docstore.retry_contention(broken)
