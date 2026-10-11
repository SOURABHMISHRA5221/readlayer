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
