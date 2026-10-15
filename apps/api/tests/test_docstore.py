"""Firestore store robustness (decision 65): read-time contention and the reader delete."""

import asyncio

import pytest
from google.api_core.exceptions import Aborted

from app.store import docstore
from app.store.docstore import FirestoreDocStore, retry_contention


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_s):
        return None

    monkeypatch.setattr(docstore.asyncio, "sleep", instant)


def attempts(*outcomes):
    calls = []

    async def attempt():
        calls.append(len(calls))  # one call = one fresh transaction (the caller builds it)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    return calls, attempt


def test_contention_raised_while_reading_is_retried():
    calls, attempt = attempts(Aborted("409 cross-transaction contention"), "ok")
    assert asyncio.run(retry_contention(attempt)) == "ok" and len(calls) == 2


def test_contention_gives_up_after_its_rounds():
    calls, attempt = attempts(*[Aborted("409")] * 3)
    with pytest.raises(Aborted):
        asyncio.run(retry_contention(attempt, rounds=2))
    assert len(calls) == 3


def test_other_errors_are_not_retried():
    calls, attempt = attempts(RuntimeError("boom"), "ok")
    with pytest.raises(RuntimeError):
        asyncio.run(retry_contention(attempt))
    assert len(calls) == 1


class FakeRef:
    def __init__(self) -> None:
        self.deleted = 0

    async def delete(self) -> None:
        self.deleted += 1


class FakeDb:
    def __init__(self, failures: int) -> None:
        self.failures, self.calls, self.ref = failures, 0, FakeRef()

    def document(self, _path):
        return self.ref

    async def recursive_delete(self, _ref):
        self.calls += 1
        if self.calls <= self.failures:
            raise Exception("BulkWriter is closed and cannot accept new operations")
        return 4


def store_with(db):
    store = FirestoreDocStore.__new__(FirestoreDocStore)
    store._db = db
    return store


def test_a_failed_reader_delete_is_tried_once_more():
    db = FakeDb(failures=1)
    assert asyncio.run(store_with(db).delete_tree("users/u1")) == 4
    assert db.calls == 2 and db.ref.deleted == 1


def test_a_reader_delete_that_fails_twice_raises():
    db = FakeDb(failures=2)
    with pytest.raises(Exception, match="BulkWriter"):
        asyncio.run(store_with(db).delete_tree("users/u1"))
    assert db.calls == 2
