"""Layer 2/3 release control: metrics, A/B judgement, canary rollout."""

from gray_release.release.ab_test import ABOutcome, evaluate_ab_test
from gray_release.release.canary import (
    BreakerTrigger,
    RolloutOutcome,
    RolloutStepRecord,
    evaluate_breaker,
    release_with_circuit_breaker,
)
from gray_release.release.metrics import (
    DialogueSample,
    InMemoryMetricsStore,
    PrometheusMetrics,
    PrometheusQueryClient,
    WindowStats,
)

__all__ = [
    "ABOutcome",
    "BreakerTrigger",
    "DialogueSample",
    "InMemoryMetricsStore",
    "PrometheusMetrics",
    "PrometheusQueryClient",
    "RolloutOutcome",
    "RolloutStepRecord",
    "WindowStats",
    "evaluate_ab_test",
    "evaluate_breaker",
    "release_with_circuit_breaker",
]
