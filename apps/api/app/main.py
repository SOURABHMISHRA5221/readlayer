"""FastAPI app: middleware, health check and the /v1 router."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response

from app.config import get_settings
from app.content.router import router as read_router
from app.graph.loader import load_graph, set_graph
from app.ingest.router import router as content_router
from app.log import configure_logging, request_id_var
from app.recs.router import router as recs_router

settings = get_settings()
configure_logging(settings.log_level)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
log = logging.getLogger("app.http")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    set_graph(await load_graph(settings.concepts_uri))
    yield


app = FastAPI(title="ReadLayer API", version="0.1.0", lifespan=lifespan)
v1 = APIRouter(prefix="/v1")


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
app.include_router(v1)
