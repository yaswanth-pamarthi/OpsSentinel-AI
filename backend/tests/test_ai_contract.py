import json
import pytest
from app import ai


class Response:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self.value}, "eval_count": 25}


class Client:
    outputs = []
    calls = []

    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def post(self, url, json):
        self.calls.append(json)
        return Response(self.outputs.pop(0))


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setattr(ai.httpx, "Client", Client)
    monkeypatch.setattr(ai.settings, "ai_mode", "ollama")
    Client.calls = []
    return Client


def test_invalid_json_repaired_once(mock_client):
    mock_client.outputs = [
        "not-json",
        json.dumps({"summary": "Evidence checked.", "limitations": [], "evidence_ids": ["valid-id"]}),
    ]
    value, metadata = ai.commentary("Contract Analysis", {"facts": "clause"}, ["valid-id"])
    assert metadata["attempts"] == 2 and value["evidence_ids"] == ["valid-id"] and len(mock_client.calls) == 2


def test_unknown_evidence_stops_after_one_retry(mock_client):
    bad = json.dumps({"summary": "Unsupported citation.", "limitations": [], "evidence_ids": ["invented-id"]})
    mock_client.outputs = [bad, bad]
    with pytest.raises(ValueError):
        ai.commentary("Contract Analysis", {}, ["valid-id"])
    assert len(mock_client.calls) == 2


def test_valid_ids_not_truncated_by_large_input(mock_client):
    mock_client.outputs = [
        json.dumps({"summary": "Bounded facts.", "limitations": [], "evidence_ids": ["valid-id"]})
    ]
    ai.commentary("Test", {"large": "x" * 20000}, ["valid-id"])
    message = json.loads(mock_client.calls[0]["messages"][1]["content"])
    assert message["valid_ids"] == ["valid-id"] and len(message["facts"]) <= 6500
    assert mock_client.calls[0]["format"]["properties"]["evidence_ids"]["items"]["enum"] == ["valid-id"]
