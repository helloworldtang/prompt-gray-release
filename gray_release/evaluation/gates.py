"""Layer 1 gate rules: pass/fail thresholds applied to eval results.

A prompt change proceeds to the 1% A/B test only when all gates pass:

* regression set -- average score must not drop more than 3% vs baseline
* edge set -- failure rate (score < fail_threshold) must stay under 5%
* new-feature set -- average must reach 0.70 (the change must deliver)
"""

from __future__ import annotations

from dataclasses import dataclass

from gray_release.config import EvaluationConfig
from gray_release.evaluation.datasets import EDGE_SET, NEW_FEATURE_SET, REGRESSION_SET
from gray_release.evaluation.runner import SetStats


@dataclass(frozen=True)
class GateOutcome:
    """Result of one gate rule.

    Attributes:
        name: Gate identifier, e.g. "regression_avg_drop".
        passed: Whether the threshold held.
        detail: Human-readable numbers behind the verdict.
    """

    name: str
    passed: bool
    detail: str


def _regression_gate(results: dict[str, SetStats], baseline: dict[str, SetStats], max_drop: float) -> GateOutcome:
    new_stats = results[REGRESSION_SET]
    baseline_stats = baseline[REGRESSION_SET]
    floor = baseline_stats.avg * (1 - max_drop)
    passed = new_stats.avg >= floor
    return GateOutcome(
        name="regression_avg_drop",
        passed=passed,
        detail=(
            f"regression avg {new_stats.avg:.3f} vs baseline {baseline_stats.avg:.3f} "
            f"(floor {floor:.3f}, max drop {max_drop:.0%})"
        ),
    )


def _edge_gate(results: dict[str, SetStats], max_fail_rate: float) -> GateOutcome:
    stats = results[EDGE_SET]
    fail_rate = stats.fail_count / stats.total if stats.total else 1.0
    passed = fail_rate <= max_fail_rate
    return GateOutcome(
        name="edge_fail_rate",
        passed=passed,
        detail=f"edge fail rate {fail_rate:.0%} ({stats.fail_count}/{stats.total}, max {max_fail_rate:.0%})",
    )


def _new_feature_gate(results: dict[str, SetStats], min_avg: float) -> GateOutcome:
    stats = results[NEW_FEATURE_SET]
    passed = stats.avg >= min_avg
    return GateOutcome(name="new_feature_avg", passed=passed, detail=f"new-feature avg {stats.avg:.3f} (min {min_avg})")


def check_gates(
    results: dict[str, SetStats],
    baseline: dict[str, SetStats],
    config: EvaluationConfig,
) -> list[GateOutcome]:
    """Evaluate all three offline gates for a candidate prompt.

    Args:
        results: Candidate prompt stats keyed by set name.
        baseline: Stable prompt stats keyed by set name (same sets required).
        config: Evaluation thresholds.

    Returns:
        One GateOutcome per gate, always three entries.

    Raises:
        KeyError: If a required set is missing from either input.
    """
    return [
        _regression_gate(results, baseline, config.gates.regression_max_avg_drop),
        _edge_gate(results, config.gates.edge_max_fail_rate),
        _new_feature_gate(results, config.gates.new_feature_min_avg),
    ]


def all_passed(outcomes: list[GateOutcome]) -> bool:
    """Return True when every gate outcome passed."""
    return all(outcome.passed for outcome in outcomes)
