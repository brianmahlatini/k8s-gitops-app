import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.logging_setup import JsonFormatter


@pytest.fixture()
def client():
    with TestClient(main.app) as c:  # runs lifespan startup/shutdown
        yield c


def test_liveness_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_readiness_fails_while_draining(client):
    main.State.ready = False
    try:
        assert client.get("/readyz").status_code == 503
        assert client.get("/healthz").status_code == 200  # liveness unaffected
    finally:
        main.State.ready = True


def test_items_crud_and_validation(client):
    assert len(client.get("/api/items").json()) >= 2
    created = client.post("/api/items", json={"name": "Test item", "price_cents": 100})
    assert created.status_code == 201
    item_id = created.json()["id"]
    assert client.get(f"/api/items/{item_id}").json()["name"] == "Test item"
    assert client.get("/api/items/999999").status_code == 404
    assert client.post("/api/items", json={"name": "", "price_cents": 1}).status_code == 422
    assert client.post("/api/items", json={"name": "x", "price_cents": -1}).status_code == 422


def test_metrics_use_route_templates_not_raw_paths(client):
    client.get("/api/items/1")
    client.get("/api/items/2")
    body = client.get("/metrics").text
    assert 'route="/api/items/{item_id}"' in body
    assert 'route="/api/items/1"' not in body
    assert "http_request_duration_seconds_bucket" in body
    assert 'route="/healthz"' not in body  # probes excluded from request metrics


def test_request_id_propagates(client):
    r = client.get("/api/info", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert client.get("/api/info").headers["x-request-id"]  # generated when absent


def test_json_log_format():
    rec = logging.LogRecord("app", logging.INFO, __file__, 1, "request", None, None)
    rec.status = 200
    rec.path = "/api/items"
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "request" and out["status"] == 200 and out["level"] == "info"


def test_settings_reject_bad_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValueError):
        Settings.from_env()
