"""Gateway endpoints, chat routing and Prometheus exposition."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gray_release.traffic.gateway import build_default_state, create_app, handle_chat
from gray_release.traffic.router import ReleaseMode, TrafficPlan


def _client(tmp_path) -> tuple[TestClient, object]:
    from gray_release.config import REPO_ROOT
    from gray_release.llm import MockLLMClient

    state = build_default_state(REPO_ROOT / "prompts", MockLLMClient())
    return TestClient(create_app(state)), state


def test_chat_serves_stable_when_plan_off() -> None:
    client, _state = _client(None)
    response = client.post("/chat", json={"user_id": "user-000001", "message": "多少钱？"})
    assert response.status_code == 200
    body = response.json()
    assert body["group"] == "control"
    assert body["version"] == "v1"
    assert body["stars"] >= 4


def test_chat_routes_treatment_users_to_new_prompt() -> None:
    client, state = _client(None)
    state.set_plan(TrafficPlan(mode=ReleaseMode.ROLLOUT, treatment_permille=1000))
    body = client.post("/chat", json={"user_id": "user-000001", "message": "多少钱？"}).json()
    assert body["version"] == "v2"


def test_plan_update_roundtrip() -> None:
    client, state = _client(None)
    response = client.post("/release/plan", json={"mode": "rollout", "treatment_permille": 200})
    assert response.status_code == 200
    status = client.get("/release/status").json()
    assert status["mode"] == "rollout"
    assert "new=20.0%" in status["summary"]


def test_plan_rejects_unknown_mode() -> None:
    client, _state = _client(None)
    assert client.post("/release/plan", json={"mode": "sideways"}).status_code == 422


def test_health_endpoint_for_rollback_script() -> None:
    client, _state = _client(None)
    assert client.get("/health").json() == {"status": "OK"}


def test_metrics_expose_chat_counters() -> None:
    client, state = _client(None)
    state.set_plan(TrafficPlan(mode=ReleaseMode.ROLLOUT, treatment_permille=1000))
    client.post("/chat", json={"user_id": "user-000001", "message": "多少钱？"})
    metrics = client.get("/metrics").text
    assert "bot_requests_total" in metrics
    assert 'version="new"' in metrics
    assert "bot_treatment_permille 1000.0" in metrics


def test_handle_chat_records_into_inmemory_store() -> None:
    from gray_release.config import REPO_ROOT
    from gray_release.llm import MockLLMClient

    state = build_default_state(REPO_ROOT / "prompts", MockLLMClient(), with_prometheus=False)
    state.set_plan(TrafficPlan(mode=ReleaseMode.AB))
    outcome = handle_chat(state, "user-000001", "贵不贵？")
    assert outcome.prompt_version == "v1"
    assert state.stats is not None
    assert state.stats.snapshot("stable", 60).requests == 1
