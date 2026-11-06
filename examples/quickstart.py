"""5 分钟跑通 prompt-gray-release 的核心闭环：

灰度路由 -> 评测门禁 -> 放量/回滚 -> 录制与确定性重演。

运行：python examples/quickstart.py
"""

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


def main() -> None:
    registry = PromptRegistry.from_yaml(Path(__file__).parent / "prompts.yaml")
    rollout = RolloutController()
    rollout.set_stable("support_reply", "v1")
    router = GrayRouter(registry, rollout)

    print("== 1. 灰度路由（v1 全量 -> v2 放量 50%）==")
    rollout.start_rollout("support_reply", "v2", 50)
    for user in ["u1", "u2", "u3", "u4"]:
        r = router.render("support_reply", {"name": user, "topic": "发票"}, user_key=user)
        print(f"  {user} -> {r.version}: {r.text.strip()}")

    print("== 2. 评测门禁（候选先跑 golden 集）==")
    gate = EvalGate(registry)
    cases = [
        EvalCase(
            {"name": "张三", "topic": "发票"},
            "你好 张三，这是 v1 的回复模板。关于 发票 的问题我们会尽快处理。",
        )
    ]
    report = gate.evaluate("support_reply", candidate="v2", baseline="v1", cases=cases)
    print(" ", report.summary())
    if report.passed:
        rollout.set_percent("support_reply", 100)
        print("  -> 放量至 100%")
    else:
        rollout.rollback("support_reply")
        print("  -> 候选版本被拦截，流量已回滚到 v1")

    print("== 3. 录制与确定性重演 ==")
    recorder = Recorder("traffic.jsonl")
    model = recorder.wrap(lambda text: f"[模拟模型] {text}")
    rendered = router.render("support_reply", {"name": "李四", "topic": "退款"}, user_key="u9")
    print("  线上调用:", model(rendered, {"name": "李四", "topic": "退款"}))

    cassette = Cassette.load("traffic.jsonl")
    for item in Replayer(cassette).replay_registry(registry):
        print(f"  重演 matches={item.matches} -> {item.rendered_now}")
    print("完成。试试改一下 prompts.yaml 里的模板再重跑第 3 步，matches 会变成 False。")


if __name__ == "__main__":
    main()
