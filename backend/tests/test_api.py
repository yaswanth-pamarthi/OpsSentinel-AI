import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core import settings


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(c, role):
    r = c.post("/auth/login", json={"email": role + "@local.demo", "password": settings.demo_password})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_protected_logs(client):
    assert client.get("/logs/search").status_code == 401


def test_commander_cannot_ingest_as_engineer(client):
    assert (
        client.post("/logs/paste", headers=login(client, "commander"), json={"text": "test"}).status_code
        == 403
    )


def test_viewer_cannot_ingest(client):
    assert (
        client.post("/logs/paste", headers=login(client, "viewer"), json={"text": "test"}).status_code == 403
    )


def test_engineer_cannot_configure_rule(client):
    assert (
        client.post(
            "/rules",
            headers=login(client, "engineer"),
            json={
                "name": "test",
                "query_type": "http",
                "threshold": 10,
                "window_seconds": 300,
                "severity": "SEV-2",
            },
        ).status_code
        == 403
    )


def test_viewer_cannot_approve(client):
    assert (
        client.post(
            "/proposals/not-real/decision",
            headers=login(client, "viewer"),
            json={"decision": "approve", "reason": "Reviewed evidence"},
        ).status_code
        == 403
    )


def test_missing_incident(client):
    assert client.get("/incidents/not-real", headers=login(client, "viewer")).status_code == 404


def test_engineer_cannot_close(client):
    assert (
        client.patch(
            "/incidents/not-real/status",
            headers=login(client, "engineer"),
            json={"status": "CLOSED", "reason": "Reviewed validation"},
        ).status_code
        == 403
    )


def test_blank_decision_reason_rejected():
    from app.schemas import DecisionIn
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DecisionIn(decision="approve", reason="       ")
