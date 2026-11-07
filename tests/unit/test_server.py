"""Framework-level smoke tests. No models, no network, no LLM calls."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from cueloom.server import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "version" in body and "uptime_sec" in body


def test_dashboard_is_served() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "CueLoom" in response.text
    assert "/api/status" in response.text


def test_status_is_redacted() -> None:
    body = client.get("/api/status").json()
    llm = body["config"]["llm"]
    assert "api_key" not in llm
    assert "CUELOOM_LLM_API_KEY" not in json.dumps(body)
    assert isinstance(llm["api_key_configured"], bool)
    assert body["pipeline"]["implemented"] is True


def test_jobs_and_artifacts_are_read_only_lists() -> None:
    assert isinstance(client.get("/api/jobs").json(), list)
    assert isinstance(client.get("/api/jobs/nonexistent-job/artifacts").json(), list)


def test_invalid_job_id_rejected() -> None:
    assert client.get("/api/jobs/%2E%2E%2Fetc").status_code in (400, 404)
