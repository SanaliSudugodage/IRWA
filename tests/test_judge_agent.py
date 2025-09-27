from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)

def test_judge_schema_and_winner():
    payload = {
        "motion": "Universal Basic Income should be implemented",
        "pro": {
            "thesis": "Pro thesis",
            "points": [
                {"text": "Evidence-backed claim", "citations": ["doc_00001#doc_00001_3"]},
                {"text": "Another claim", "citations": []}
            ]
        },
        "con": {
            "thesis": "Con thesis",
            "points": [
                {"text": "Bold claim without evidence", "citations": []}
            ]
        }
    }
    r = client.post("/agents/judge", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "pro_breakdown" in data and "con_breakdown" in data
    assert "winner" in data and data["winner"] in ["pro", "con"]
    for crit in data["pro_breakdown"]:
        assert 0 <= crit["score"] <= 5 and len(crit["explanation"]) > 0 #########################
