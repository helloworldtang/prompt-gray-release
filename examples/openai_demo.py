"""用真实模型跑通全流程：灰度路由 -> 真实调用（录制）-> 评测门禁 -> 确定性重演。

库本身不依赖 openai——本示例单独安装：

    pip install openai
    export OPENAI_API_KEY=sk-...            # 必填
    export OPENAI_BASE_URL=https://...      # 可选：任意 OpenAI 兼容端点
    export PGR_MODEL=gpt-4o-mini            # 可选，默认 gpt-4o-mini

运行：python examples/openai_demo.py
"""

from __future__ import annotations

import os
from pathlib import Path

from prompt_gray_release import (
    Cassette,
    EvalCase,
    EvalGate,
    GrayRouter,
    PromptRegistry,
    Recorder,
    Replayer,
    RolloutController,
)

TRAFFIC = Path(__file__).parent / "openai_traffic.jsonl"


def make_model() -> object:
    """返回一个 model(text) -> response 的真实模型函数（OpenAI 兼容端点）。"""
    from openai import OpenAI  # noqa: PLC0415 —— 示例单独安装，不进库依赖

    client = OpenAI()  # 自动读取 OPENAI_API_KEY / OPENAI_BASE_URL
    model_name = os.environ.get("PGR_MODEL", "gpt-4o-mini")

    def model(text: str) -> str:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": text}],
            temperature=0,
        )
        return resp.choices[0].message.content or ""

    return model


def main() -> None:
    registry = PromptRegistry.from_yaml(Path(__file__).parent / "prompts.yaml")

    # 1) 灰度：v2 先放 30%，同一用户永远同一版本
    rollout = RolloutController(state_path=Path(__file__).parent / "openai_state.json")
    if not rollout.has("support_reply"):
        rollout.set_stable("support_reply", "v1")
    if not rollout.state("support_reply").candidate:
        rollout.start_rollout("support_reply", "v2", 30)
    router = GrayRouter(registry, rollout)

    # 2) 真实模型调用 + 调用即录制（业务流量才录制，裁判调用走裸模型）
    raw_model = make_model()
    recorder = Recorder(TRAFFIC)
    model = recorder.wrap(raw_model)
    variables = {"name": "张三", "topic": "发票"}
    rendered = router.render("support_reply", variables, user_key="user-42")
    print(f"[{rendered.version}] 发给真实模型: {rendered.text.strip()}")
    response = model(rendered, variables)
    print(f"模型响应: {response.strip()[:120]}…")

    # 3) 评测门禁：候选 v2 与 stable v1 各渲染一遍，交给真实模型当裁判
    def llm_evaluator(output: str, expected: str) -> float:
        """裁判：输出是否回应了 expected 描述的要点（0 / 0.5 / 1）。

        注意用裸模型——裁判调用混进 traffic.jsonl 会污染重演门禁的带子。
        """
        judge_prompt = (
            "判断下面的回复是否回应了用户诉求，只回答 0（没有）、0.5（部分）或 1（完全）。\n"
            f"用户诉求：{expected}\n回复：{output}\n只输出数字。"
        )
        verdict = raw_model(judge_prompt).strip()
        return float(verdict) if verdict in {"0", "0.5", "1"} else 0.0

    gate = EvalGate(registry)
    cases = [EvalCase(variables, "问候用户并承诺处理发票问题")]
    report = gate.evaluate(
        "support_reply", candidate="v2", baseline="v1", cases=cases, evaluator=llm_evaluator
    )
    print("门禁:", report.summary())
    if report.passed:
        print("-> 可继续放量（prompt-gray set-percent support_reply 100 --state ...）")
    else:
        rollout.rollback("support_reply")
        print("-> 已回滚到 stable")

    # 4) 确定性重演：之后随时重放录制，不再花一分钱调模型
    cassette = Cassette.load(TRAFFIC)
    for item in Replayer(cassette).replay_registry(registry):
        print(f"重演 matches={item.matches}（False = 有人改过模板）")
    print(f"审计与流量已落盘: {TRAFFIC} / {rollout.state_path}")


if __name__ == "__main__":
    main()
