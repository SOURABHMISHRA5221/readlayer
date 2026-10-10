"""FastAPI app: middleware, health check and the /v1 router."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import ratelimit
from app.auth import get_auth_admin
from app.config import get_settings
from app.content.router import router as read_router
from app.explain.router import router as explain_router
from app.graph.loader import get_graph, load_graph, set_graph
from app.ingest.router import router as content_router
from app.log import configure_logging, request_id_var
from app.me.onboarding import router as onboarding_router
from app.me.profile_edit import router as profile_edit_router
from app.me.router import router as me_router
from app.recs.router import router as recs_router

settings = get_settings()
configure_logging(settings.log_level)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
log = logging.getLogger("app.http")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    start = time.perf_counter()
    set_graph(await load_graph(settings.concepts_uri))
    grown = 0
    if settings.concepts_uri:  # concepts grown online since the file was written (M2.2)
        from app.graph.refresh import get_refresher

        grown = await get_refresher().load_startup()
    graph_ms = (time.perf_counter() - start) * 1000
    get_auth_admin()
    log.info(
        "startup",
        extra={
            "graph_load_ms": round(graph_ms, 1),
            "graph_version": get_graph().version,
            "grown_concepts": grown,
            "startup_ms": round((time.perf_counter() - start) * 1000, 1),
            "cors_origins": settings.cors_origin_list,
        },
    )
    yield


app = FastAPI(title="ReadLayer API", version="0.1.0", lifespan=lifespan)
# Every /v1 route needs a Firebase ID token (the general limit depends on the caller) and
# counts against the per-uid general rate limit. Only /health is public.
v1 = APIRouter(prefix="/v1", dependencies=[Depends(ratelimit.general)])


def _request_id(request: Request) -> str:
    if rid := request.headers.get("x-request-id"):
        return rid[:64]
    # Cloud Run sets "TRACE_ID/SPAN_ID;o=1".
    if trace := request.headers.get("x-cloud-trace-context"):
        return trace.split("/", 1)[0][:64]
    return uuid.uuid4().hex


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    rid = _request_id(request)
    token = request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error", extra={"method": request.method, "path": request.url.path})
        raise
    else:
        response.headers["X-Request-ID"] = rid
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "uid_hash": getattr(request.state, "uid_hash", None),
            },
        )
        return response
    finally:
        request_id_var.reset(token)


# Cloud Run's front end reserves /healthz (returns its own 404), so /health is the public probe.
@app.get("/health")
@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


v1.include_router(content_router)
v1.include_router(read_router)
v1.include_router(recs_router)
v1.include_router(explain_router)
v1.include_router(me_router)
v1.include_router(onboarding_router)
v1.include_router(profile_edit_router)
app.include_router(v1)

# Added last so it wraps everything: preflights and error responses carry CORS headers too.
# Only the web app's origins (Hosting in prod); no cookies, so no credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
    max_age=600,
)
