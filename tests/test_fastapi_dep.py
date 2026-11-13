"""prompt_dep：FastAPI 依赖注入的 HTTP 契约。

质量点：一行接入后，路由语义（稳定分桶 / 不猜 / fail-fast）与直接调
``router.render`` 一致，且错误按 HTTP 语义分层（422 形状 / 400 缺变量 /
500 配置问题）。
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from prompt_gray_release import GrayRouter, RenderedPrompt, prompt_dep


def make_client(registry, rollout) -> TestClient:
    dep = prompt_dep("support_reply", GrayRouter(registry, rollout))
    app = FastAPI()

    @app.post("/reply")
    def reply(r: RenderedPrompt = Depends(dep)) -> dict[str, object]:
        return {"version": r.version, "percent": r.percent, "prompt": r.text}

    return TestClient(app)


def test_dep_renders_with_user_key_and_variables(registry, rollout):
    rollout.start_rollout("support_reply", "v2", 100)
    client = make_client(registry, rollout)

    resp = client.post(
        "/reply", json={"user_key": "u1", "variables": {"name": "张三", "topic": "发票"}}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "v2"  # 100% 灰度，全部走 candidate
    assert body["percent"] == 100
    assert "张三" in body["prompt"]


def test_dep_without_user_key_at_partial_percent_serves_stable(registry, rollout):
    rollout.start_rollout("support_reply", "v2", 50)
    client = make_client(registry, rollout)

    resp = client.post("/reply", json={"variables": {"name": "张三", "topic": "发票"}})

    assert resp.status_code == 200
    assert resp.json()["version"] == "v1"  # 无 user_key 不猜，宁可不灰度


def test_dep_missing_variable_is_400(registry, rollout):
    client = make_client(registry, rollout)

    resp = client.post("/reply", json={"user_key": "u1", "variables": {}})

    assert resp.status_code == 400
    assert "模板缺少变量" in resp.json()["detail"]


def test_dep_non_json_body_is_422(registry, rollout):
    client = make_client(registry, rollout)

    resp = client.post("/reply", content=b"not json", headers={"Content-Type": "text/plain"})

    assert resp.status_code == 422


def test_dep_non_object_body_is_422(registry, rollout):
    client = make_client(registry, rollout)

    resp = client.post("/reply", json=[1, 2])

    assert resp.status_code == 422


def test_dep_wrong_field_types_are_422(registry, rollout):
    client = make_client(registry, rollout)

    resp = client.post("/reply", json={"user_key": 42, "variables": {}})

    assert resp.status_code == 422
