"""Typed configuration for the gray release pipeline.

Every threshold enforced by the gates (evaluation/gates.py), the A/B judge
(release/ab_test.py) and the circuit breaker (release/canary.py) lives in
config/release_config.yaml and is loaded into the models below, so no
release-critical number is hard-coded where ops cannot tune it.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "release_config.yaml"


class DatasetRefreshConfig(BaseModel):
    """Cadence for refreshing eval sets from production logs (pit #1)."""

    keep_ratio: float = 0.8
    refresh_interval_days: int = 7


class EvalGatesConfig(BaseModel):
    """Layer 1 thresholds: a prompt change must pass all three gates."""

    regression_max_avg_drop: float = 0.03
    edge_max_fail_rate: float = 0.05
    new_feature_min_avg: float = 0.70


class EvaluationConfig(BaseModel):
    """Offline evaluation settings."""

    fail_threshold: float = 0.70
    gates: EvalGatesConfig = Field(default_factory=EvalGatesConfig)
    dataset_refresh: DatasetRefreshConfig = Field(default_factory=DatasetRefreshConfig)


class ABTestConfig(BaseModel):
    """Layer 2 thresholds: 1% A/B traffic and its success criteria."""

    a_permille: int = 5
    b_permille: int = 5
    min_improvement: float = 0.05
    max_response_time_degradation: float = 0.10
    min_observation_seconds: int = 86400
    min_sample: int = 30


class RolloutConfig(BaseModel):
    """Layer 3 ramp-up plan. Steps are never skipped (pit #3)."""

    steps: list[int] = Field(default_factory=lambda: [5, 20, 50, 100])
    observe_seconds: int = 14400


class CircuitBreakerConfig(BaseModel):
    """Trip conditions for rolling back to the last stable prompt."""

    satisfaction_ratio: float = 0.95
    completion_ratio: float = 0.95
    response_time_ratio: float = 1.5
    max_error_rate: float = 0.05
    window_seconds: int = 3600
    min_sample: int = 20
    cooldown_seconds: int = 86400


class ReleaseConfig(BaseModel):
    """Root configuration aggregating all three layers."""

    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    ab_test: ABTestConfig = Field(default_factory=ABTestConfig)
    rollout: RolloutConfig = Field(default_factory=RolloutConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)


def load_config(path: Path | None = None) -> ReleaseConfig:
    """Load the release config from YAML, falling back to field defaults.

    Args:
        path: Config file location. Defaults to config/release_config.yaml
            at the repository root.

    Returns:
        A validated ReleaseConfig. Missing sections fall back to the same
        defaults the YAML file documents.
    """
    config_path = path if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return ReleaseConfig()
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping: {config_path}")
    return ReleaseConfig.model_validate(raw)
