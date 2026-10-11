"""generate_image (decision 44 V3): offline, with a fake LiteLLM and the in-memory ledger."""

import base64
import struct
from types import SimpleNamespace

import litellm
import pytest

from app import llm
from app.store.spend_repo import InMemorySpendStore


def png(width: int, height: int) -> bytes:
    """Just enough PNG for the header check: signature and IHDR."""
    return (
        b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
    )


def jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + bytes(9)
    sof = b"\xff\xc0" + struct.pack(">HBHH", 11, 8, height, width) + bytes(4)
    return b"\xff\xd8" + app0 + sof


def reply(*images: bytes, mime: str = "image/png") -> SimpleNamespace:
    items = [
        {"image_url": {"url": f"data:{mime};base64,{base64.b64encode(i).decode()}"}} for i in images
    ]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="", images=items))],
        usage=SimpleNamespace(prompt_tokens=300, completion_tokens=1290),
    )


class FakeImages:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, script: list, cost: float = 0.0) -> None:
        self.script, self.calls = list(script), []
        monkeypatch.setattr(litellm, "acompletion", self.acompletion)
        monkeypatch.setattr(litellm, "completion_cost", lambda **_: cost)

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def image_settings(settings):
    return settings.model_copy(update={"model_image": "vertex_ai/image", "llm_max_retries": 2})


async def test_refuses_when_the_budget_is_spent(monkeypatch, image_settings):
    llm.set_spend_store(InMemorySpendStore(initial_usd=1.0))  # == budget
    fake = FakeImages(monkeypatch, [reply(png(1024, 1024))])
    try:
        with pytest.raises(llm.BudgetExceeded):
            await llm.generate_image("landing_art", {"scene": "x"}, settings=image_settings)
    finally:
        llm.set_spend_store(None)
    assert fake.calls == []


async def test_missing_or_invalid_images_are_retried_then_rejected(
    monkeypatch, image_settings, spend
):
    fake = FakeImages(monkeypatch, [reply(), reply(b"not an image"), reply(png(100, 100))])
    with pytest.raises(llm.LLMRejected):
        await llm.generate_image("landing_art", {"scene": "x"}, settings=image_settings)
    assert len(fake.calls) == 3  # 1 + llm_max_retries, each one charged
    assert spend.calls == 3


async def test_a_retry_that_returns_a_good_image_succeeds(monkeypatch, image_settings, spend):
    FakeImages(
        monkeypatch, [reply(png(10, 10), png(10, 10)), reply(jpeg(1024, 768), mime="image/jpeg")]
    )
    result = await llm.generate_image("landing_art", {"scene": "x"}, settings=image_settings)
    assert (result.mime, result.width, result.height, result.attempts) == (
        "image/jpeg",
        1024,
        768,
        2,
    )
    assert result.prompt_version == "landing-art-v1"


async def test_charges_the_configured_price_per_image_when_litellm_cannot_price_it(
    monkeypatch, image_settings, spend
):
    FakeImages(monkeypatch, [reply(png(1024, 1024))], cost=0.0)
    result = await llm.generate_image("landing_art", {"scene": "x"}, settings=image_settings)
    assert result.cost_usd == pytest.approx(image_settings.model_image_price_usd)
    assert spend.total == pytest.approx(image_settings.model_image_price_usd)


async def test_uses_litellm_price_when_it_has_one(monkeypatch, image_settings, spend):
    FakeImages(monkeypatch, [reply(png(1024, 1024))], cost=0.05)
    result = await llm.generate_image("landing_art", {"scene": "x"}, settings=image_settings)
    assert result.cost_usd == pytest.approx(0.05)


async def test_the_prompt_holds_only_the_scene_and_the_reference(
    monkeypatch, image_settings, spend
):
    fake = FakeImages(monkeypatch, [reply(png(1024, 1024))])
    ref = png(512, 512)
    await llm.generate_image(
        "landing_art", {"scene": "a shredder"}, reference_png=ref, settings=image_settings
    )
    call = fake.calls[0]
    assert call["model"] == "vertex_ai/image"
    assert call["modalities"] == ["image", "text"]
    user = call["messages"][-1]["content"]
    text = [p["text"] for p in user if p["type"] == "text"][0]
    assert "a shredder" in text
    assert [p["image_url"]["url"] for p in user if p["type"] == "image_url"] == [
        "data:image/png;base64," + base64.b64encode(ref).decode()
    ]
    # Nothing from articles or readers: the only variable is the scene.
    assert llm._PLACEHOLDER.findall(llm.load_prompt("landing_art").user) == ["scene"]


async def test_no_model_configured_is_unavailable(image_settings, spend):
    with pytest.raises(llm.LLMUnavailable):
        await llm.generate_image(
            "landing_art",
            {"scene": "x"},
            settings=image_settings.model_copy(update={"model_image": ""}),
        )


def test_image_size_reads_png_and_jpeg_headers():
    assert llm.image_size(png(640, 480)) == ("image/png", 640, 480)
    assert llm.image_size(jpeg(800, 600)) == ("image/jpeg", 800, 600)
    assert llm.image_size(b"GIF89a") is None
