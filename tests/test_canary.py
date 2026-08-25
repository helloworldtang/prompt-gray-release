"""Layer 3: breaker evaluation and the circuit-breaker rollout loop."""

from __future__ import annotations

from gray_release.config import CircuitBreakerConfig, ReleaseConfig
from gray_release.release.canary import evaluate_breaker, release_with_circuit_breaker
from gray_release.release.metrics import WindowStats


def _stats(
    requests: int = 100,
    satisfaction: float = 4.0,
    completion: float = 0.80,
    response_time: float = 0.8,
    error_rate: float = 0.0,
) -> WindowStats:
    return WindowStats(
        requests=requests,
        satisfaction=satisfaction,
        completion_rate=completion,
        response_time=response_time,
        error_rate=error_rate,
    )


def test_healthy_new_prompt_trips_nothing() -> None:
    triggers = evaluate_breaker(_stats(satisfaction=4.2, completion=0.85), _stats(), CircuitBreakerConfig())
    assert triggers == []


def test_completion_drop_trips() -> None:
    triggers = evaluate_breaker(_stats(completion=0.70), _stats(completion=0.85), CircuitBreakerConfig())
    assert [trigger.condition for trigger in triggers] == ["completion_drop"]


def test_satisfaction_drop_trips() -> None:
    triggers = evaluate_breaker(_stats(satisfaction=3.5), _stats(satisfaction=4.0), CircuitBreakerConfig())
    assert [trigger.condition for trigger in triggers] == ["satisfaction_drop"]


def test_response_time_spike_trips() -> None:
    triggers = evaluate_breaker(_stats(response_time=1.5), _stats(response_time=0.8), CircuitBreakerConfig())
    assert [trigger.condition for trigger in triggers] == ["response_time_spike"]


def test_error_rate_trips() -> None:
    triggers = evaluate_breaker(_stats(error_rate=0.06), _stats(), CircuitBreakerConfig())
    assert [trigger.condition for trigger in triggers] == ["error_rate"]


def test_zero_baseline_skips_ratio_conditions() -> None:
    triggers = evaluate_breaker(_stats(requests=10), WindowStats.empty(), CircuitBreakerConfig())
    assert triggers == []


def _config(steps: list[int]) -> ReleaseConfig:
    config = ReleaseConfig()
    config.rollout.steps = steps
    config.rollout.observe_seconds = 0
    return config


def test_rollout_completes_when_healthy() -> None:
    applied: list[int] = []
    outcome = release_with_circuit_breaker(
        config=_config([5, 50, 100]),
        stats_source=lambda label, window: _stats(requests=100, satisfaction=4.2 if label == "new" else 4.0),
        on_step=applied.append,
    )
    assert not outcome.rolled_back
    assert outcome.reached_percentage == 100
    assert applied == [5, 50, 100]


def test_rollout_rolls_back_on_trip() -> None:
    applied: list[int] = []

    def stats(label: str, window: int) -> WindowStats:
        # Healthy during warm-up, collapses at 20%.
        if label == "new":
            return _stats(requests=100, completion=0.60)
        return _stats(requests=100, completion=0.85)

    outcome = release_with_circuit_breaker(
        config=_config([5, 20, 50]),
        stats_source=stats,
        on_step=applied.append,
    )
    assert outcome.rolled_back
    assert applied[-1] == 0  # rollback resets traffic to the stable prompt
    assert outcome.triggers
    assert outcome.cooldown_seconds == ReleaseConfig().circuit_breaker.cooldown_seconds


def test_small_sample_skips_evaluation() -> None:
    outcome = release_with_circuit_breaker(
        config=_config([5, 100]),
        stats_source=lambda label, window: (
            WindowStats(requests=3, satisfaction=1.0, completion_rate=0.0, response_time=9.0, error_rate=0.9)
            if label == "new"
            else _stats()
        ),
        on_step=lambda percentage: None,
    )
    # Catastrophic stats were ignored because the sample was below min_sample.
    assert not outcome.rolled_back
    assert all(not step.evaluated for step in outcome.steps)
