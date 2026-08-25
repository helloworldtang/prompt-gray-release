"""End-to-end replay of the incident this project exists to prevent.

Story being replayed:

1. A product-description prompt is rewritten; offline evals pass because the
   eval set is three months stale and contains no long-tail pricing
   phrasings. It ships straight to full traffic.
2. Next morning, conversion is down 15%: users asking "贵不贵" / "有什么优
   倪" get a feature pitch instead of a price, and nobody knows which change
   caused it.

The demo then replays the same v2 prompt through the three-layer pipeline
(eval gates -> 1% A/B -> progressive rollout) and shows where each layer
catches what it catches -- including the circuit breaker rolling the release
back and writing the post-mortem.
"""

from __future__ import annotations

from pathlib import Path

from gray_release.config import REPO_ROOT, ReleaseConfig, load_config
from gray_release.evaluation.datasets import load_test_set
from gray_release.evaluation.gates import GateOutcome, all_passed, check_gates
from gray_release.evaluation.runner import evaluate_prompt, render_report
from gray_release.llm import MockLLMClient
from gray_release.release.ab_test import evaluate_ab_test
from gray_release.release.canary import release_with_circuit_breaker
from gray_release.release.metrics import InMemoryMetricsStore
from gray_release.release.postmortem import write_postmortem
from gray_release.replay import (
    AB_TEST_DIALOGUES,
    AB_TEST_MIX,
    PRODUCTION_MIX,
    ROLLOUT_DIALOGUES_PER_STEP,
    FakeClock,
    collect_group_users,
    message_sequence,
    replay_chats,
)
from gray_release.traffic.gateway import build_default_state
from gray_release.traffic.router import ReleaseMode, TrafficPlan

SEPARATOR = "=" * 72


def _banner(title: str) -> None:
    print(f"\n{SEPARATOR}\n{title}\n{SEPARATOR}")


def _gate_lines(outcomes: list[GateOutcome]) -> None:
    for outcome in outcomes:
        verdict = "PASS" if outcome.passed else "FAIL"
        print(f"  [{verdict}] {outcome.name}: {outcome.detail}")


def _demo_rollout_config(config: ReleaseConfig) -> ReleaseConfig:
    """Compress observation windows so the demo runs instantly."""
    tweaked = config.model_copy(deep=True)
    tweaked.rollout.observe_seconds = 0
    return tweaked


def run_demo(output_dir: Path | None = None) -> None:
    """Run the full incident replay and the three-layer pipeline.

    Args:
        output_dir: Directory for the generated post-mortem; defaults to
            postmortems/ under the repo root.
    """
    config = load_config()
    clock = FakeClock()
    store = InMemoryMetricsStore(clock=clock)
    client = MockLLMClient()
    state = build_default_state(REPO_ROOT / "prompts", client, store=store, with_prometheus=False)

    stable_prompt = (REPO_ROOT / "prompts" / "product_desc_v1.txt").read_text(encoding="utf-8")
    new_prompt = (REPO_ROOT / "prompts" / "product_desc_v2.txt").read_text(encoding="utf-8")

    fresh_sets = {
        "regression": load_test_set(REPO_ROOT / "datasets" / "regression.jsonl"),
        "edge": load_test_set(REPO_ROOT / "datasets" / "edge_cases.jsonl"),
        "new_feature": load_test_set(REPO_ROOT / "datasets" / "new_feature.jsonl"),
    }
    stale_sets = dict(fresh_sets)
    stale_sets["regression"] = load_test_set(REPO_ROOT / "datasets" / "regression_stale.jsonl")

    _banner("第 0 幕 · 事故当晚（上周二）：改了 Prompt，测试没问题，直接全量")
    baseline_stale = evaluate_prompt(stable_prompt, stale_sets, client, config.evaluation.fail_threshold)
    candidate_stale = evaluate_prompt(new_prompt, stale_sets, client, config.evaluation.fail_threshold)
    print(render_report(candidate_stale, "v2 在当时的（过期）评测集上"))
    _gate_lines(check_gates(candidate_stale, baseline_stale, config.evaluation))
    print("  → 三道门槛全过，当晚全量上线。第二天转化率 -15%。")

    _banner("第 1 层 · 离线评测：如果评测集每周更新（保留 80% 旧 + 20% 新）")
    baseline_fresh = evaluate_prompt(stable_prompt, fresh_sets, client, config.evaluation.fail_threshold)
    candidate_fresh = evaluate_prompt(new_prompt, fresh_sets, client, config.evaluation.fail_threshold)
    print(render_report(candidate_fresh, "v2 在每周更新的评测集上（含长尾问法）"))
    outcomes = check_gates(candidate_fresh, baseline_fresh, config.evaluation)
    _gate_lines(outcomes)
    if not all_passed(outcomes):
        worst = sorted(candidate_fresh["regression"].scores, key=lambda pair: pair[1])[:3]
        worst_ids = ", ".join(case_id for case_id, _ in worst)
        print(f"  → 回归门槛拦截！15 分钟内结束战斗。最低分 case: {worst_ids}（正是长尾问法）")
    else:
        print("  → 意外：未拦截（数值校准漂移，请检查 mock 答案与 checklist）")

    _banner("第 2 层 · 1% A/B：A=0.5% 新 Prompt，B=0.5% 旧 Prompt（一致性哈希分组）")
    ab_plan = TrafficPlan(
        mode=ReleaseMode.AB,
        ab_a_permille=config.ab_test.a_permille,
        ab_b_permille=config.ab_test.b_permille,
    )
    state.set_plan(ab_plan)
    print(f"  流量计划：{ab_plan.summary()}，其余 99% 不参与测试")
    messages = message_sequence(AB_TEST_DIALOGUES, AB_TEST_MIX)
    a_users = collect_group_users(ab_plan, "A", AB_TEST_DIALOGUES)
    b_users = collect_group_users(ab_plan, "B", AB_TEST_DIALOGUES)
    replay_chats(state, a_users, messages)
    replay_chats(state, b_users, messages)
    huge_window = 10**9
    ab_outcome = evaluate_ab_test(
        store.snapshot("new", huge_window),
        store.snapshot("stable", huge_window),
        config.ab_test,
    )
    print(
        f"  A组(新) 满意度 {ab_outcome.new_stats.satisfaction:.2f} / 完成率 {ab_outcome.new_stats.completion_rate:.0%}"
        f"  |  B组(旧) 满意度 {ab_outcome.old_stats.satisfaction:.2f} / 完成率 {ab_outcome.old_stats.completion_rate:.0%}"
    )
    for reason in ab_outcome.reasons:
        print(f"  - {reason}")
    print(f"  → A/B 判定：{'通过，进入放量' if ab_outcome.passed else '不通过，发布终止'}")
    print("    （小样本里长尾问法只占 5%，没暴露问题——这就是滞后的用户反馈）")

    _banner("第 3 层 · 渐进放量 + 自动熔断：5% → 20% → 50% → 100%")
    # Slide the A/B dialogues out of the breaker window first: they carried
    # the A group's inflated scores, and the breaker must judge rollout
    # traffic against rollout traffic.
    clock.advance(config.circuit_breaker.window_seconds + 1)
    next_user_index = 0

    def on_step(percentage: int) -> None:
        if percentage <= 0:
            state.set_plan(TrafficPlan(mode=ReleaseMode.OFF))
        else:
            state.set_plan(TrafficPlan(mode=ReleaseMode.ROLLOUT, treatment_permille=percentage * 10))

    def generate_traffic(percentage: int) -> None:
        nonlocal next_user_index
        users = [f"user-{i:06d}" for i in range(next_user_index, next_user_index + ROLLOUT_DIALOGUES_PER_STEP)]
        next_user_index += ROLLOUT_DIALOGUES_PER_STEP
        served = replay_chats(state, users, message_sequence(ROLLOUT_DIALOGUES_PER_STEP, PRODUCTION_MIX))
        print(f"  真实流量涌入（长尾问法占 35%）：{served} 条对话")

    outcome = release_with_circuit_breaker(
        config=_demo_rollout_config(config),
        stats_source=store.snapshot,
        on_step=on_step,
        generate_traffic=generate_traffic,
        # Observation windows are compressed to one second per step; the
        # breaker still reads a full trailing window, so step N's judgement
        # covers step N plus any earlier traffic still inside the window --
        # the same overlapping-window semantics as production.
        sleep_fn=lambda _seconds: clock.advance(1),
        log=lambda line: print(f"  {line}" if not line.startswith("rollout") else line),
    )

    if outcome.rolled_back:
        directory = output_dir if output_dir is not None else REPO_ROOT / "postmortems"
        postmortem_path = write_postmortem(outcome, store.worst_samples(10, "new"), directory)
        for trigger in outcome.triggers:
            print(f"  熔断条件：[{trigger.condition}] {trigger.detail}")
        print(f"  → 已回滚到稳定版 v1，冷却 {outcome.cooldown_seconds // 3600}h")
        print(f"  → Post-mortem 已生成：{postmortem_path}")
        print("    对应真实事故里的『转化率 -15%』——这次 20% 流量就被拦下，损失缩小 5 倍。")
    else:
        print("  → 放量顺利完成（demo 预期会在 20% 熔断，若看到此行请检查数值校准）")

    _banner("总结：快（实时监控）· 狠（自动熔断）· 稳（三层灰度）")
    print("  1. 离线评测 15 分钟 —— 评测集每周更新时，第一层就能拦住本次事故")
    print("  2. 1% A/B 24 小时 —— 覆盖昼夜与工作日/周末的问法分布")
    print("  3. 5%→20%→50%→100% —— 每步观察+自动熔断，问题最多损失 20% 流量的一天")
