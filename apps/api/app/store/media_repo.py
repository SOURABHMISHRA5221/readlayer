"""Shared media counters and memory per UTC day (Media plan R5, 2.2). No uid anywhere.

ops/media/days/{day}   `anonymous`: recordings opened by demo readers (the shared cap, through
                       ReaderRepo.reserve_daily); `refused`: {content_id: code} for every
                       refusal found that day, so a refused URL is never looked up or paid for
                       again. Bounded by the lookup cap plus the items transcribed.
ops/search/days/{day}  `media_lookup`: videos.list calls, Apple lookups and audio pre-checks,
                       counted apart from `calls` and `youtube` so search caps are untouched.
"""

from app.store.docstore import DocStore, Txn, get_doc_store


def media_day_path(day: str) -> str:
    return f"ops/media/days/{day}"


def _search_day_path(day: str) -> str:
    return f"ops/search/days/{day}"


LOOKUP_FIELD = "media_lookup"


class MediaDayRepo:
    def __init__(self, store: DocStore) -> None:
        self._store = store

    async def refusal(self, content_id: str, day: str) -> str | None:
        doc = await self._store.get(media_day_path(day)) or {}
        code = (doc.get("refused") or {}).get(content_id)
        return str(code) if code else None

    async def remember_refusal(self, content_id: str, code: str, day: str) -> None:
        async def body(t: Txn) -> None:
            path = media_day_path(day)
            doc = await t.get(path) or {}
            t.set(path, doc | {"refused": {**(doc.get("refused") or {}), content_id: code}})

        await self._store.run(body)

    async def anonymous_opened(self, day: str) -> int:
        doc = await self._store.get(media_day_path(day)) or {}
        return int(doc.get("anonymous", 0))

    async def reserve_lookup(self, day: str, cap: int) -> bool:
        """Count one media lookup against the shared daily cap. False = cap reached."""

        async def body(t: Txn) -> bool:
            path = _search_day_path(day)
            doc = await t.get(path) or {}
            used = int(doc.get(LOOKUP_FIELD, 0))
            if used >= cap:
                return False
            t.set(path, doc | {LOOKUP_FIELD: used + 1})
            return True

        return await self._store.run(body)


def get_media_day_repo() -> MediaDayRepo:
    return MediaDayRepo(get_doc_store())
