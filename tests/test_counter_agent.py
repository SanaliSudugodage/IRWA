# tests/test_counter_agent.py
import json
from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)

def test_counter_contract_structured_ok():
    payload = {
        "motion": "Universal Basic Income should be implemented",
        "opponent": {
            "thesis": "UBI has no downsides.",
            "points": [
                {"text": "UBI never reduces labor supply.", "citations": []},
                {"text": "It will always eliminate poverty.", "citations": ["doc_00003#doc_00003_5"]}
            ]
        }
    }
    r = client.post("/agents/counter", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    # contract checks
    assert "weaknesses" in data and isinstance(data["weaknesses"], list)
    assert "rebuttals" in data and isinstance(data["rebuttals"], list)
    assert all("target_point_index" in w for w in data["weaknesses"])
    assert all("counterclaim" in rb and "citations" in rb for rb in data["rebuttals"])

def test_counter_contract_legacy_points_ok():
    payload = {
        "motion": "Universal Basic Income should be implemented",
        "opponent_points": [
            "UBI never reduces labor supply.",
            "It will always eliminate poverty."
        ]
    }
    r = client.post("/agents/counter", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "weaknesses" in data and "rebuttals" in data
    assert len(data["weaknesses"]) == 2
    assert len(data["rebuttals"]) == 2 
