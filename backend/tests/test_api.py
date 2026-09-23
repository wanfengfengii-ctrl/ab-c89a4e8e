"""API contract tests: endpoints, 422 field locations, health."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_solve_basic():
    resp = client.post(
        "/api/solve",
        json={
            "messages": [
                {"id": "a", "C": 1, "T": 4, "D": 4, "J": 0},
                {"id": "b", "C": 2, "T": 6, "D": 6, "J": 0},
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["order"] == ["a", "b"]
    assert body["objective"]["deadline_misses"] == 0
    assert body["search"]["total_permutations"] == 2
    assert {r["id"] for r in body["results"]} == {"a", "b"}


def test_422_duplicate_id_locates_field():
    resp = client.post(
        "/api/solve",
        json={
            "messages": [
                {"id": "x", "C": 1, "T": 4, "D": 4, "J": 0},
                {"id": "x", "C": 2, "T": 6, "D": 6, "J": 0},
            ]
        },
    )
    assert resp.status_code == 422
    locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
    assert ("body", "messages", 1, "id") in locs


def test_422_c_d_t_ordering():
    resp = client.post(
        "/api/solve",
        json={
            "messages": [
                {"id": "a", "C": 3, "T": 5, "D": 2, "J": 0},
                {"id": "b", "C": 2, "T": 6, "D": 6, "J": 0},
            ]
        },
    )
    assert resp.status_code == 422
    err = next(e for e in resp.json()["detail"] if e["loc"][-1] == "D")
    assert err["loc"][:3] == ["body", "messages", 0]


def test_422_jitter_bound():
    resp = client.post(
        "/api/solve",
        json={
            "messages": [
                {"id": "a", "C": 3, "T": 8, "D": 5, "J": 3},  # D-C=2
                {"id": "b", "C": 2, "T": 6, "D": 6, "J": 0},
            ]
        },
    )
    assert resp.status_code == 422
    err = next(e for e in resp.json()["detail"] if e["loc"][-1] == "J")
    assert err["loc"][2] == 0


def test_422_count_out_of_range():
    resp = client.post(
        "/api/solve",
        json={"messages": [{"id": "a", "C": 1, "T": 4, "D": 4, "J": 0}]},
    )
    assert resp.status_code == 422


def test_422_primitive_range_and_type():
    resp = client.post(
        "/api/solve",
        json={
            "messages": [
                {"id": "a", "C": 0, "T": 4, "D": 4, "J": 0},
                {"id": "b", "C": 2, "T": 6, "D": 6, "J": 0},
            ]
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"][-1] == "C"

    resp = client.post(
        "/api/solve",
        json={
            "messages": [
                {"id": "a", "C": "oops", "T": 4, "D": 4, "J": 0},
                {"id": "b", "C": 2, "T": 6, "D": 6, "J": 0},
            ]
        },
    )
    assert resp.status_code == 422


def test_422_analyze_bad_permutation():
    payload = {
        "messages": [
            {"id": "a", "C": 1, "T": 4, "D": 4, "J": 0},
            {"id": "b", "C": 2, "T": 6, "D": 6, "J": 0},
        ],
        "order": ["a", "c"],
    }
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"][-1] == "order"


def test_analyze_given_order_matches_solver_payload():
    msgs = [
        {"id": "a", "C": 1, "T": 4, "D": 4, "J": 0},
        {"id": "b", "C": 2, "T": 6, "D": 6, "J": 0},
    ]
    solved = client.post("/api/solve", json={"messages": msgs}).json()
    resp = client.post(
        "/api/analyze", json={"messages": msgs, "order": solved["order"]}
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == solved["results"]
