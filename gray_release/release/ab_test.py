"""Layer 2: judge the 1% A/B test.

The A group (0.5%) runs the new prompt, the B group (0.5%) the old one;
everybody else stays on the stable prompt and is excluded. The test passes
only when the new prompt beats the old one by at least min_improvement on
BOTH satisfaction and task completion, without degrading response time by
more than max_response_time_degradation -- all judged over an observation
window of at least min_observation_seconds covering day/night patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gray_release.config import ABTestConfig
from gray_release.release.metrics import WindowStats


@dataclass(frozen=True)
class ABOutcome:
    """Verdict of an A/B test evaluation.

    Attributes:
        passed: Whether the new prompt may advance to progressive rollout.
        reasons: Human-readable findings, one per criterion.
        new_stats: Aggregated stats of the A group (new prompt).
        old_stats: Aggregated stats of the B group (old prompt).
        satisfaction_lift: Relative satisfaction change, e.g. 0.12 for +12%.
        completion_lift: Relative task-completion change.
        response_time_delta: Relative response-time change; positive is bad.
    """

    passed: bool
    new_stats: WindowStats
    old_stats: WindowStats
    satisfaction_lift: float
    completion_lift: float
    response_time_delta: float
    reasons: list[str] = field(default_factory=list)


def _lift(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old


def evaluate_ab_test(new_stats: WindowStats, old_stats: WindowStats, config: ABTestConfig) -> ABOutcome:
    """Judge whether the A/B result justifies starting the rollout.

    Args:
        new_stats: A-group (new prompt) window stats.
        old_stats: B-group (old prompt) window stats.
        config: Success criteria and minimum sample sizes.

    Returns:
        An ABOutcome whose passed flag gates progression to layer 3.
    """
    satisfaction_lift = _lift(new_stats.satisfaction, old_stats.satisfaction)
    completion_lift = _lift(new_stats.completion_rate, old_stats.completion_rate)
    response_time_delta = _lift(new_stats.response_time, old_stats.response_time)
    reasons: list[str] = []

    if new_stats.requests < config.min_sample or old_stats.requests < config.min_sample:
        reasons.append(
            f"insufficient sample: A={new_stats.requests}, B={old_stats.requests} dialogues (< {config.min_sample})"
        )
    if satisfaction_lift < config.min_improvement:
        reasons.append(f"satisfaction lift {satisfaction_lift:+.1%} below required +{config.min_improvement:.0%}")
    if completion_lift < config.min_improvement:
        reasons.append(f"completion lift {completion_lift:+.1%} below required +{config.min_improvement:.0%}")
    if response_time_delta > config.max_response_time_degradation:
        reasons.append(
            f"response time degraded {response_time_delta:+.1%} beyond allowed "
            f"+{config.max_response_time_degradation:.0%}"
        )

    passed = not reasons
    if passed:
        reasons.append(
            f"new prompt wins on satisfaction ({satisfaction_lift:+.1%}) and completion "
            f"({completion_lift:+.1%}) without latency regression ({response_time_delta:+.1%})"
        )
    return ABOutcome(
        passed=passed,
        new_stats=new_stats,
        old_stats=old_stats,
        satisfaction_lift=satisfaction_lift,
        completion_lift=completion_lift,
        response_time_delta=response_time_delta,
        reasons=reasons,
    )
