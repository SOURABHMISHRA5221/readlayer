"""Cold starts stay short: importing the API and serving read paths never loads the ingestion
libraries (spaCy, trafilatura, wordfreq) or LiteLLM. Runs in a fresh interpreter, because this
test session has already imported everything."""

import json
import subprocess
import sys
from pathlib import Path

HEAVY = ("spacy", "trafilatura", "wordfreq", "litellm")

IMPORT_ONLY = f"""
import json, sys
import app.main
print(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))
"""

READ_PATHS = f"""
import json, os, sys
os.environ["LITELLM_MODE"] = "PRODUCTION"
from fastapi.testclient import TestClient
from app import auth
from app.content import router as read_router
from app.graph.loader import set_graph
from app.main import app
from app.recs import web_search as ws
from app.store import docstore
from app.store.content_repo import InMemoryContentStore, set_content_store
from tests.fake_auth import FakeAuthAdmin, auth as headers
from tests.test_recs_library import DOCS, GRAPH
from app.config import get_settings

docstore.set_doc_store(docstore.InMemoryDocStore())
auth.set_auth_admin(FakeAuthAdmin())
store = InMemoryContentStore()
store.docs = {{d.content_id: d for d in DOCS}}
set_content_store(store)
read_router.reset_catalog()
set_graph(GRAPH)
ws.set_web_search(ws.WebSearch({{}}, ws.InMemoryRecCache(), ws.InMemorySearchCalls(),
                                get_settings(), frozenset()))
codes = []
for anonymous in (True, False):
    c = TestClient(app, headers=headers("u-" + str(anonymous), anonymous))
    for path in ("/v1/content", "/v1/content/main", "/v1/content/main/annotations",
                 "/v1/content/main/recommendations", "/v1/me/profile", "/v1/me/graph",
                 "/v1/me/graph?domain=finance", "/v1/me/export"):
        codes.append(c.get(path).status_code)
loaded = [m for m in {HEAVY!r} if m in sys.modules]
print(json.dumps({{"codes": sorted(set(codes)), "loaded": loaded}}))
"""


def _run(code: str) -> object:
    env = {"PATH": "/usr/bin:/bin", "GCP_PROJECT": "test-project", "LITELLM_MODE": "PRODUCTION"}
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_importing_the_app_loads_no_ingestion_library():
    assert _run(IMPORT_ONLY) == []


def test_read_paths_load_no_ingestion_library():
    result = _run(READ_PATHS)
    assert result == {"codes": [200], "loaded": []}
