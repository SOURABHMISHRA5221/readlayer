"""Every HTTP method a /v1 route uses must pass CORS: the web app calls the API cross-origin in
production (Vite proxies it locally, so a missing method only fails live; PUT /v1/me/saved did)."""

from fastapi.middleware.cors import CORSMiddleware

from app.main import app


def test_cors_allows_every_method_the_api_uses():
    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    allowed = set(cors.kwargs["allow_methods"])
    paths = app.openapi()["paths"]
    used = {m.upper() for path, ops in paths.items() if path.startswith("/v1") for m in ops}
    assert {"GET", "POST", "PUT", "PATCH", "DELETE"} <= used  # the schema really lists the routes
    assert used <= allowed, f"not allowed by CORS: {sorted(used - allowed)}"


def test_the_extension_origin_passes_when_configured():
    """M8 §A4: CORS_ORIGINS gains chrome-extension://<id>; its worker calls with a bearer token."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.config import Settings

    ext = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    origins = Settings(cors_origins=f"https://readlayer.web.app, {ext}/").cors_origin_list
    assert origins == ["https://readlayer.web.app", ext]
    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    probe = FastAPI()
    probe.add_middleware(CORSMiddleware, **{**cors.kwargs, "allow_origins": origins})
    headers = {
        "Origin": ext,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    ok = TestClient(probe).options("/v1/content", headers=headers)
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == ext
    other = {**headers, "Origin": "chrome-extension://someoneelse"}
    assert TestClient(probe).options("/v1/content", headers=other).status_code == 400
