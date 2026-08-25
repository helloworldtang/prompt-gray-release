"""Layer 3: progressive rollout with an automatic circuit breaker.

Ramp-up walks the configured steps (5% -> 20% -> 50% -> 100%, never skipping
-- pit #3). After each observation window the new prompt's windowed stats are
compared against the stable version running as control traffic; any tripped
condition rolls traffic back to the stable prompt (on_step(0)) and stops the
release for the cooldown period.

Every dependency is injected (stats source, plan setter, sleep, traffic
generator) so tests run in microseconds and the demo compresses 4-hour
observation windows into a single clock jump.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from gray_release.config import CircuitBreakerConfig, ReleaseConfig
from gray_release.release.metrics import WindowStats


@dataclass(frozen=True)
class BreakerTrigger:
    """One tripped breaker condition.

    Attributes:
        condition: Machine name, e.g. "completion_drop".
        detail: Human-readable numbers behind the trip.
    """

    condition: str
    detail: str


@dataclass(frozen=True)
class RolloutStepRecord:
    """What happened at one rollout step.

    Attributes:
        percentage: Treatment percentage this step set.
        evaluated: False when the new version had too few samples to judge.
        new_stats: New-prompt stats in the window (None when skipped).
        stable_stats: Stable-prompt (control) stats in the window.
        triggers: Conditions that tripped at this step.
    """

    percentage: int
    evaluated: bool
    new_stats: WindowStats | None
    stable_stats: WindowStats | None
    triggers: list[BreakerTrigger] = field(default_factory=list)


@dataclass
class RolloutOutcome:
    """Final result of a canary run.

    Attributes:
        rolled_back: True when the breaker tripped and traffic went back to
            the stable prompt.
        reached_percentage: Last percentage that was set before completion
            or rollback (0 after rollback).
        steps: Per-step records, in order.
        triggers: Triggers of the fatal step (empty on success).
        cooldown_seconds: Pause required after a rollback before retrying.
    """

    rolled_back: bool
    reached_percentage: int
    steps: list[RolloutStepRecord] = field(default_factory=list)
    triggers: list[BreakerTrigger] = field(default_factory=list)
    cooldown_seconds: int = 0


def evaluate_breaker(
    new_stats: WindowStats,
    stable_stats: WindowStats,
    config: CircuitBreakerConfig,
) -> list[BreakerTrigger]:
    """Check all four trip conditions for the new prompt.

    Args:
        new_stats: Windowed stats of the new prompt (treatment traffic).
        stable_stats: Windowed stats of the stable prompt (control traffic).
        config: Trip thresholds.

    Returns:
        Triggers for every violated condition; empty list means healthy.
    """
    triggers: list[BreakerTrigger] = []

    if stable_stats.satisfaction > 0 and new_stats.satisfaction < stable_stats.satisfaction * config.satisfaction_ratio:
        triggers.append(
            BreakerTrigger(
                condition="satisfaction_drop",
                detail=(
                    f"satisfaction {new_stats.satisfaction:.2f} < "
                    f"{stable_stats.satisfaction:.2f} * {config.satisfaction_ratio}"
                ),
            )
        )
    if (
        stable_stats.completion_rate > 0
        and new_stats.completion_rate < stable_stats.completion_rate * config.completion_ratio
    ):
        triggers.append(
            BreakerTrigger(
                condition="completion_drop",
                detail=(
                    f"completion {new_stats.completion_rate:.0%} < "
                    f"{stable_stats.completion_rate:.0%} * {config.completion_ratio}"
                ),
            )
        )
    if (
        stable_stats.response_time > 0
        and new_stats.response_time > stable_stats.response_time * config.response_time_ratio
    ):
        triggers.append(
            BreakerTrigger(
                condition="response_time_spike",
                detail=(
                    f"response time {new_stats.response_time:.2f}s > "
                    f"{stable_stats.response_time:.2f}s * {config.response_time_ratio}"
                ),
            )
        )
    if new_stats.error_rate > config.max_error_rate:
        triggers.append(
            BreakerTrigger(
                condition="error_rate",
                detail=f"error rate {new_stats.error_rate:.0%} > {config.max_error_rate:.0%}",
            )
        )
    return triggers


def release_with_circuit_breaker(
    *,
    config: ReleaseConfig,
    stats_source: Callable[[str, int], WindowStats],
    on_step: Callable[[int], None],
    generate_traffic: Callable[[int], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> RolloutOutcome:
    """Drive the ramp-up, evaluating the breaker after every step.

    Args:
        config: Release configuration (steps, observe window, breaker).
        stats_source: Callable(version_label, window_seconds) -> WindowStats;
            production wires PrometheusQueryClient, the demo uses the
            in-memory store.
        on_step: Applies a treatment percentage; 0 means full rollback to
            the stable prompt. Called with each step value and with 0 on
            rollback.
        generate_traffic: Optional hook invoked right after on_step so the
            demo can synthesize production-like traffic per step; real
            rollouts leave it None.
        sleep_fn: Observation wait; the demo jumps its fake clock instead of
            sleeping.
        log: Optional progress sink.

    Returns:
        RolloutOutcome describing how far the release got and why it stopped.
    """

    def emit(message: str) -> None:
        if log is not None:
            log(message)

    window = config.circuit_breaker.window_seconds
    breaker = config.circuit_breaker
    steps: list[RolloutStepRecord] = []
    reached = 0

    emit(f"rollout plan: {config.rollout.steps} (observe {config.rollout.observe_seconds}s per step)")
    for percentage in config.rollout.steps:
        on_step(percentage)
        reached = percentage
        emit(f"ramping to {percentage}% ...")
        if generate_traffic is not None:
            generate_traffic(percentage)
        if sleep_fn is not None:
            sleep_fn(config.rollout.observe_seconds)

        new_stats = stats_source("new", window)
        if new_stats.requests < breaker.min_sample:
            emit(
                f"  only {new_stats.requests} new-prompt samples (< {breaker.min_sample}); skipping breaker evaluation"
            )
            steps.append(
                RolloutStepRecord(percentage=percentage, evaluated=False, new_stats=new_stats, stable_stats=None)
            )
            continue

        stable_stats = stats_source("stable", window)
        triggers = evaluate_breaker(new_stats, stable_stats, breaker)
        steps.append(
            RolloutStepRecord(
                percentage=percentage,
                evaluated=True,
                new_stats=new_stats,
                stable_stats=stable_stats,
                triggers=triggers,
            )
        )
        if triggers:
            on_step(0)
            for trigger in triggers:
                emit(f"  BREAKER TRIPPED at {percentage}%: [{trigger.condition}] {trigger.detail}")
            emit("rolled back to the last stable prompt; rollout paused for cooldown")
            return RolloutOutcome(
                rolled_back=True,
                reached_percentage=0,
                steps=steps,
                triggers=triggers,
                cooldown_seconds=breaker.cooldown_seconds,
            )
        emit(
            f"  healthy at {percentage}% (satisfaction {new_stats.satisfaction:.2f}, completion {new_stats.completion_rate:.0%})"
        )

    emit("reached 100%; release complete")
    return RolloutOutcome(rolled_back=False, reached_percentage=reached, steps=steps)
