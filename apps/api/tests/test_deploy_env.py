"""Decision 62: two Firebase Hosting sites serve the same build, so CORS must allow both (on
both domains) and nothing else but the Gloss extension; a site added without CORS fails here."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _deploy_origins() -> set[str]:
    text = (ROOT / "apps/api/deploy.env.yaml").read_text()
    line = re.search(r"^CORS_ORIGINS:\s*(.+)$", text, re.M)
    assert line, "CORS_ORIGINS missing from deploy.env.yaml"
    return {o.strip() for o in line.group(1).split(",") if o.strip()}


def _hosting_sites() -> set[str]:
    rc = json.loads((ROOT / ".firebaserc").read_text())
    targets = rc["targets"][rc["projects"]["default"]]["hosting"]
    return {site for sites in targets.values() for site in sites}


def _extension_origin() -> str:
    web = (ROOT / "apps/web/src/lib/extension.ts").read_text()
    ext_id = re.search(r'EXTENSION_ID = "([a-p]{32})"', web)
    assert ext_id
    return f"chrome-extension://{ext_id.group(1)}"


def test_cors_is_exactly_the_hosting_sites_and_the_extension():
    sites = _hosting_sites()
    assert sites == {"readlayer-sourabh-26", "glossreader"}
    expected = {f"https://{s}.{d}" for s in sites for d in ("web.app", "firebaseapp.com")}
    assert _deploy_origins() == expected | {_extension_origin()}


def test_both_hosting_entries_serve_the_same_build():
    hosting = json.loads((ROOT / "firebase.json").read_text())["hosting"]
    rc = json.loads((ROOT / ".firebaserc").read_text())
    mapped = rc["targets"][rc["projects"]["default"]]["hosting"]
    assert sorted(h["target"] for h in hosting) == sorted(mapped)
    bodies = [{k: v for k, v in h.items() if k != "target"} for h in hosting]
    assert all(b == bodies[0] for b in bodies)
