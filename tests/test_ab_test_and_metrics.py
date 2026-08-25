"""Layer 2: A/B judgement; plus windowed metrics and sample retention."""

from __future__ import annotations

from gray_release.config import ABTestConfig
from gray_release.release.ab_test import evaluate_ab_test
from gray_release.release.metrics import DialogueSample, InMemoryMetricsStore, WindowStats
from gray_release.replay import FakeClock


def _stats(requests: int, satisfaction: float, completion: float, response_time: float) -> WindowStats:
    return WindowStats(
        requests=requests,
        satisfaction=satisfaction,
        completion_rate=completion,
        response_time=response_time,
        error_rate=0.0,
    )


def test_ab_passes_when_new_wins_on_both_metrics() -> None:
    outcome = evaluate_ab_test(
        _stats(60, 4.80, 0.95, 0.60),
        _stats(60, 3.35, 0.65, 0.80),
        ABTestConfig(),
    )
    assert outcome.passed
    assert outcome.satisfaction_lift == 0.43283582089552256 or outcome.satisfaction_lift > 0.43


def test_ab_fails_on_completion_regression() -> None:
    outcome = evaluate_ab_test(
        _stats(60, 4.80, 0.95, 0.60),
        _stats(60, 4.00, 1.00, 0.80),
        ABTestConfig(),
    )
    assert not outcome.passed
    assert any("completion lift" in reason for reason in outcome.reasons)


def test_ab_fails_on_latency_regression() -> None:
    outcome = evaluate_ab_test(
        _stats(60, 4.80, 0.95, 1.00),  # 25% slower than old
        _stats(60, 3.35, 0.65, 0.80),
        ABTestConfig(),
    )
    assert not outcome.passed
    assert any("response time" in reason for reason in outcome.reasons)


def test_ab_fails_on_insufficient_sample() -> None:
    outcome = evaluate_ab_test(_stats(5, 5.0, 1.0, 0.1), _stats(5, 1.0, 0.0, 1.0), ABTestConfig())
    assert not outcome.passed
    assert any("insufficient sample" in reason for reason in outcome.reasons)


def test_window_snapshot_excludes_old_records() -> None:
    clock = FakeClock()
    store = InMemoryMetricsStore(clock=clock)
    store.record(version_label="new", group="treatment", stars=1, completed=False, response_time=0.5)
    clock.advance(3_601)  # first record now falls outside a 3600s window
    store.record(version_label="new", group="treatment", stars=5, completed=True, response_time=0.5)
    stats = store.snapshot("new", 3_600)
    assert stats.requests == 1
    assert stats.satisfaction == 5.0


def test_snapshot_empty_window_returns_empty_stats() -> None:
    store = InMemoryMetricsStore(clock=FakeClock())
    stats = store.snapshot("new", 60)
    assert stats.requests == 0
    assert stats.satisfaction == 0.0


def test_worst_samples_filtered_by_version() -> None:
    store = InMemoryMetricsStore(clock=FakeClock())
    for index in range(4):
        store.record(
            version_label="new" if index % 2 else "stable",
            group="treatment",
            stars=1,
            completed=False,
            response_time=0.5,
            user_id=f"user-{index}",
            message="贵不贵？",
            answer="...",
        )
    new_only = store.worst_samples(10, "new")
    assert all(sample.version_label == "new" for sample in new_only)
    assert len(new_only) == 2
    assert {sample.user_id for sample in new_only} == {"user-1", "user-3"}


def test_high_star_dialogues_are_not_retained_as_samples() -> None:
    store = InMemoryMetricsStore(clock=FakeClock())
    store.record(
        version_label="new",
        group="treatment",
        stars=5,
        completed=True,
        response_time=0.5,
        message="多少钱",
        answer="好答案",
    )
    assert store.worst_samples(10) == []


def test_dialogue_sample_dataclass_fields() -> None:
    sample = DialogueSample(user_id="u1", message="m", answer="a", stars=1, version_label="new")
    assert (sample.user_id, sample.stars) == ("u1", 1)
