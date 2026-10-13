"""API tests that need no network: catalogues, validation, health, community CRUD, SPA fallback."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["crops"] >= 30 and body["diseases"] >= 15


def test_crop_catalogue(client):
    r = client.get("/api/twin/crops")
    assert r.status_code == 200
    crops = r.json()["crops"]
    assert any(c["id"] == "rice" for c in crops)
    assert all({"label", "seasons", "tips", "price_t"} <= set(c) for c in crops)
    assert {"IN", "US", "UK", "EU", "WORLD"} <= set(r.json()["regions"])


def test_simulate_rejects_unknown_crop_before_network(client):
    r = client.post("/api/twin/simulate", json={"lat": 26.1, "lon": 87.5, "scenario": {"crop": "rice", "sow_date": "2026-06-20", "area_ha": -1}})
    assert r.status_code == 422


def test_scan_rejects_non_image(client):
    r = client.post("/api/scan/leaf", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_community_roundtrip(client):
    r = client.post("/api/community/posts", data={"title": "Leaf curl on tomato", "body": "Started after the heat wave.", "topic": "pest", "crop": "tomato", "author": "Test"})
    assert r.status_code == 201
    pid = r.json()["id"]
    r = client.post(f"/api/community/posts/{pid}/comments", json={"author": "Neighbour", "body": "Check for whitefly under the leaves."})
    assert r.status_code == 201 and r.json()["comment_count"] == 1
    r = client.post(f"/api/community/posts/{pid}/upvote")
    assert r.json()["upvotes"] == 1
    r = client.get("/api/community/posts", params={"topic": "pest"})
    assert any(p["id"] == pid for p in r.json()["posts"])
    r = client.post("/api/community/posts", data={"title": "bad", "body": "bad", "topic": "nope"})
    assert r.status_code == 422


def test_spa_fallback_serves_shell(client):
    r = client.get("/some/deep/route")
    assert r.status_code == 200 and "<title>FarmIQ</title>" in r.text
    assert client.get("/manifest.webmanifest").status_code == 200
