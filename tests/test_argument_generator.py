# tests/test_argument_generator.py
from __future__ import annotations

from fastapi.testclient import TestClient

from src.app import app

client = TestClient(app)


def test_generate_argument_basic_ok():
    payload = {
        "motion": "Universal Basic Income should be implemented",
        "stance": "pro",
        "rounds": 3
    }
    resp = client.post("/agents/argument", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Basic structure checks
    assert "thesis" in data and isinstance(data["thesis"], str)
    assert "points" in data and isinstance(data["points"], list)
    assert len(data["points"]) >= 1

    # Each point: text + citations (list)
    for p in data["points"]:
        assert "text" in p and isinstance(p["text"], str)
        assert "citations" in p and isinstance(p["citations"], list)
        # citations can be empty for now (stub), so just type-check


def test_generate_argument_works_without_stance():
    payload = {
        "motion": "Universal Basic Income should be implemented"
        # stance omitted
    }
    resp = client.post("/agents/argument", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "Position on" in data["thesis"]
################################################
################################################
