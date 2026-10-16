"""Decision 67 A6: warm_demo --for-you asks for the For you frame, trader and policy student."""

import json

import httpx

from scripts import warm_demo


def test_for_you_personas_and_request_body():
    assert warm_demo.personas_for("for_you") == ("trader", "policy_student")
    assert "newcomer" in warm_demo.personas_for("pick")


async def test_explain_sends_the_frame_only_for_for_you():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"cached": False, "kind": "verified"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await warm_demo.explain(client, "http://api", "c1", "d1", "trader", 0, "for_you")
        await warm_demo.explain(client, "http://api", "c1", "d1", "trader", 1)
    assert seen == [
        {"content_id": "c1", "demand_id": "d1", "frame": "for_you"},
        {"content_id": "c1", "demand_id": "d1", "shift": 1},
    ]
