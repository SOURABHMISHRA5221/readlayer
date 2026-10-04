import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.log import JsonFormatter, hash_uid, uid_hash_var
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("path", ["/healthz", "/health"])
def test_health(path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_request_id_propagates(caplog):
    with caplog.at_level(logging.INFO, logger="app.http"):
        resp = client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert resp.headers["X-Request-ID"] == "abc123"
    record = next(r for r in caplog.records if r.getMessage() == "request")
    line = json.loads(JsonFormatter().format(record))
    assert line["path"] == "/healthz" and line["status"] == 200 and "latency_ms" in line


def test_request_id_generated_when_absent():
    assert len(client.get("/healthz").headers["X-Request-ID"]) == 32


def test_hash_uid_is_stable_salted_and_short():
    assert hash_uid("u1", "s") == hash_uid("u1", "s")
    assert hash_uid("u1", "s") != hash_uid("u1", "t")
    assert len(hash_uid("u1", "s")) == 16 and "u1" not in hash_uid("u1", "s")


def test_formatter_emits_context_and_extras():
    token = uid_hash_var.set("h123")
    try:
        record = logging.makeLogRecord({"msg": "x", "levelname": "INFO", "task": "smoke"})
        line = json.loads(JsonFormatter().format(record))
    finally:
        uid_hash_var.reset(token)
    assert line["severity"] == "INFO" and line["uid_hash"] == "h123" and line["task"] == "smoke"
