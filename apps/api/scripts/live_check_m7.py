"""Live check for M7 against the deployed API (or a local one).

    uv run python -m scripts.live_check_m7 [--api URL]

One Firebase anonymous (demo) user, deleted in `finally` (DELETE /v1/me). Checks the demo side of
M7; the signed-in flow (consent, onboarding, calibration, delete → consent) is Sourabh's own live
check with his Google account.

1. The trader's profile: onboarding done, the persona's frame (cricket) in thinks_in and summary.
2. The knowledge map for finance: ≤ 60 nodes, edges closed, nodes carry `recent` evidence.
3. A session-only profile edit: preview changes nothing; apply sets the session frame and style;
   undo restores both; reset returns the persona to the original. One profile_edit call
   (≈ $0.001) and +1 on the shared anonymous counter ops/profile_edit/days/{day} (not deleted).
4. Signed-in-only routes refuse a demo reader (onboarding 403).
"""

import argparse
import asyncio
from typing import Any

import httpx

from scripts.live_check_explain import API, sign_in_anonymously

TEXT = "I'm a backend engineer and I like short explanations"


async def checks(client: httpx.AsyncClient, api: str) -> None:
    async def get(path: str) -> dict[str, Any]:
        resp = await client.get(f"{api}{path}")
        resp.raise_for_status()
        return resp.json()

    profile = await get("/v1/me/profile?persona=trader")
    print(
        "1. profile", profile["onboarding"], profile["thinks_in"], "|", profile["summary"]["text"]
    )
    assert profile["onboarding"]["done"] is True and profile["thinks_in"] == ["cricket"]

    graph = await get("/v1/me/graph?domain=finance&persona=trader")
    ids = {n["id"] for n in graph["nodes"]}
    closed = all(e["from"] in ids and e["to"] in ids for e in graph["edges"])
    with_recent = sum(bool(n["recent"]) for n in graph["nodes"])
    print(f"2. map: {len(ids)} nodes, edges closed {closed}, {with_recent} with recent evidence")
    assert len(ids) <= 60 and closed and all("recent" in n for n in graph["nodes"])

    edit = await client.post(f"{api}/v1/me/profile/edits?persona=trader", json={"text": TEXT})
    edit.raise_for_status()
    body = edit.json()
    print("3. preview", body["preview"]["settings"], "unresolved", body["preview"]["unresolved"])
    assert (await get("/v1/me/profile?persona=trader"))["thinks_in"] == ["cricket"]  # unchanged
    eid = body["edit_id"]
    applied = await client.post(f"{api}/v1/me/profile/edits/{eid}/apply?persona=trader")
    applied.raise_for_status()
    after = await get("/v1/me/profile?persona=trader")
    print(
        "   applied: thinks_in", after["thinks_in"], "style", after["settings"]["explanation_style"]
    )
    undone = await client.post(f"{api}/v1/me/profile/edits/{eid}/undo?persona=trader")
    undone.raise_for_status()
    restored = await get("/v1/me/profile?persona=trader")
    print(
        "   undone: thinks_in",
        restored["thinks_in"],
        "style",
        restored["settings"]["explanation_style"],
    )
    assert after["thinks_in"] == ["software"] and after["settings"]["explanation_style"] == "short"
    assert restored["thinks_in"] == ["cricket"]
    assert restored["settings"]["explanation_style"] == "normal"
    reset = await client.post(f"{api}/v1/me/demo/reset", json={"persona": "trader"})
    print("   reset", reset.json())
    assert reset.status_code == 200

    refused = await client.post(f"{api}/v1/onboarding", json={"field": "software"})
    print("4. onboarding as a demo reader →", refused.status_code)
    assert refused.status_code == 403


async def emulator_sign_in(client: httpx.AsyncClient) -> str:
    """The local harness (make dev-emulator): an anonymous user in the Auth emulator."""
    url = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo-key"
    resp = await client.post(url, json={"returnSecureToken": True})
    resp.raise_for_status()
    return resp.json()["idToken"]


async def run(api: str, emulator: bool) -> None:
    async with httpx.AsyncClient(timeout=90) as client:
        token = await (emulator_sign_in(client) if emulator else sign_in_anonymously(client))
        client.headers["Authorization"] = f"Bearer {token}"
        try:
            await checks(client, api)
            print("ALL LIVE CHECKS PASSED")
        finally:
            resp = await client.delete(f"{api}/v1/me")
            print(f"cleanup: DELETE /v1/me → {resp.status_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    parser.add_argument(
        "--emulator", action="store_true", help="sign in on the local Auth emulator"
    )
    args = parser.parse_args()
    asyncio.run(run(args.api.rstrip("/"), args.emulator))


if __name__ == "__main__":
    main()
