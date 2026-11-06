"""FastAPI 集成示例：把灰度路由嵌进请求处理（10 行级核心，可选安装 fastapi）。

    pip install fastapi uvicorn prompt-gray-release
    uvicorn examples.fastapi_app:app

    curl "http://127.0.0.1:8000/reply?name=%E5%BC%A0%E4%B8%89&topic=%E5%8F%91%E7%A5%A8"
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from prompt_gray_release import GrayRouter, PromptRegistry, RolloutController

app = FastAPI()

# 启动时装配：注册表 + 灰度状态（带持久化与审计）
registry = PromptRegistry.from_yaml(Path(__file__).parent / "prompts.yaml")
rollout = RolloutController(state_path=Path(__file__).parent / "fastapi_state.json")
if not rollout.has("support_reply"):
    rollout.set_stable("support_reply", "v1")
    rollout.start_rollout("support_reply", "v2", 30)  # v2 灰度 30%
router = GrayRouter(registry, rollout)


@app.get("/reply")
def reply(name: str, topic: str, user_key: str = "") -> dict[str, str]:
    # 核心就这一行：按 user_key 稳定分桶，同一用户永远同一版本
    r = router.render("support_reply", {"name": name, "topic": topic}, user_key=user_key or name)
    return {"version": r.version, "prompt": r.text, "model": str(r.metadata.get("model", ""))}


@app.get("/__rollback")
def rollback() -> dict[str, str]:
    """出问题时的秒级回滚入口（生产上应加鉴权）。"""
    rollout.rollback("support_reply")
    return {"status": "rolled back to " + rollout.state("support_reply").stable}
