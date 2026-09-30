"""Demo service with the operational surface a platform expects:
liveness vs readiness, Prometheus metrics, JSON logs, request ids and a
graceful-shutdown window for Kubernetes endpoint propagation."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from app import logging_setup
from app.config import Settings

settings = Settings.from_env()
logging_setup.configure(settings.log_level)
log = logging.getLogger("app")

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
IN_FLIGHT = Gauge("http_requests_in_flight", "Requests currently being served")
BUILD_INFO = Gauge("app_build_info", "Build metadata", ["version", "env"])
BUILD_INFO.labels(settings.version, settings.app_env).set(1)


class State:
    ready = False


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    State.ready = True
    log.info("started", extra={"path": "-", "status": 0})
    yield
    # SIGTERM: stop advertising readiness first so the Service drops us,
    # while in-flight requests finish (preStop in the Deployment adds a delay).
    State.ready = False
    log.info("shutting down")


app = FastAPI(title="k8s-gitops-app", version=settings.version, lifespan=lifespan)


@app.middleware("http")
async def observe(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    start = time.perf_counter()
    IN_FLIGHT.inc()
    status = 500
    try:
        response: Response = await call_next(request)
        status = response.status_code
    finally:
        IN_FLIGHT.dec()
        # Label by route *template* (/api/items/{item_id}), never the raw path:
        # raw paths make metric cardinality unbounded.
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - start
        if template not in ("/metrics", "/healthz", "/readyz"):
            REQUESTS.labels(request.method, template, str(status)).inc()
            LATENCY.labels(request.method, template).observe(elapsed)
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": template,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                    "request_id": request_id,
                },
            )
    response.headers["x-request-id"] = request_id
    return response


# ------------------------------------------------------------------ probes
@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness: the process can serve. Never checks dependencies, or a
    database blip would restart every pod at once."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz(response: Response) -> dict[str, str]:
    """Readiness: should this pod receive traffic right now?"""
    if not State.ready:
        response.status_code = 503
        return {"status": "draining"}
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# -------------------------------------------------------------- demo API
class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price_cents: int = Field(ge=0, le=10_000_000)


class Item(ItemIn):
    id: int


_items: dict[int, Item] = {
    1: Item(id=1, name="Sample widget", price_cents=1999),
    2: Item(id=2, name="Sample gadget", price_cents=4999),
}


@app.get("/api/items")
def list_items() -> list[Item]:
    return sorted(_items.values(), key=lambda i: i.id)


@app.get("/api/items/{item_id}")
def get_item(item_id: int) -> Item:
    item = _items.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@app.post("/api/items", status_code=201)
def create_item(body: ItemIn) -> Item:
    item = Item(id=max(_items, default=0) + 1, **body.model_dump())
    _items[item.id] = item
    return item


@app.get("/api/info")
def info() -> dict[str, str]:
    return {"version": settings.version, "env": settings.app_env}
