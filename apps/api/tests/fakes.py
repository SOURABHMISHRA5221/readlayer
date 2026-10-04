"""Shared fakes for ingestion tests: a scripted demand extractor in place of the LLM."""

from typing import Any

from app import llm
from app.ingest.demands import DemandExtraction


def meta(model: str = "vertex_ai/fast", cost: float = 0.0004) -> llm.CallMeta:
    return llm.CallMeta(
        task="extract_demands",
        model=model,
        prompt_version="extract_demands-v1",
        tokens_in=1200,
        tokens_out=300,
        cost_usd=cost,
        latency_ms=5.0,
        fell_back=False,
        attempts=1,
    )


class FakeLLM:
    """Replaces llm.run_with_meta. `reply(prompt_vars)` builds the output dict per call."""

    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply = reply or (lambda _vars: {"paragraphs": []})
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, task, schema, prompt_vars, **_):
        self.calls.append({"task": task, "vars": prompt_vars})
        if self.error:
            raise self.error
        output = DemandExtraction.model_validate(self.reply(prompt_vars))
        return llm.LLMResult(output, meta())


class FakeAuthAdmin:
    """Accepts tokens shaped "test:<provider>:<uid>"; anything else is invalid."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.users: set[str] = set()

    async def verify(self, token: str) -> dict:
        from app.auth import InvalidToken

        parts = token.split(":", 2)
        if len(parts) != 3 or parts[0] != "test":
            raise InvalidToken("InvalidIdTokenError")
        _, provider, uid = parts
        if uid in self.deleted:
            raise InvalidToken("UserNotFoundError")
        self.users.add(uid)
        return {
            "uid": uid,
            "email": f"{uid}@example.com",
            "firebase": {"sign_in_provider": provider},
        }

    async def delete_user(self, uid: str) -> None:
        self.deleted.append(uid)
        self.users.discard(uid)


def token(uid: str = "u1", anonymous: bool = False) -> str:
    return f"test:{'anonymous' if anonymous else 'google.com'}:{uid}"


def auth(uid: str = "u1", anonymous: bool = False) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(uid, anonymous)}"}
