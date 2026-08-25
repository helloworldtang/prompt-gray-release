"""Layer 1: evaluation runner and gate rules against the repo's datasets.

These tests lock in the incident calibration: on the stale set v2 passes
every gate (that is how the incident shipped), on the weekly-refreshed set
the regression gate blocks it (that is how the pipeline prevents it).
"""

from __future__ import annotations

from pathlib import Path

from gray_release.config import load_config
from gray_release.evaluation.datasets import load_test_set
from gray_release.evaluation.gates import all_passed, check_gates
from gray_release.evaluation.runner import evaluate_prompt, load_baseline, render_report, save_baseline


def _load_sets(repo_root: Path, regression_file: str) -> dict[str, list]:
    return {
        "regression": load_test_set(repo_root / "datasets" / regression_file),
        "edge": load_test_set(repo_root / "datasets" / "edge_cases.jsonl"),
        "new_feature": load_test_set(repo_root / "datasets" / "new_feature.jsonl"),
    }


def test_v2_passes_all_gates_on_stale_set(repo_root: Path, mock_client, prompts) -> None:
    sets = _load_sets(repo_root, "regression_stale.jsonl")
    baseline = evaluate_prompt(prompts["v1"], sets, mock_client, 0.7)
    candidate = evaluate_prompt(prompts["v2"], sets, mock_client, 0.7)
    outcomes = check_gates(candidate, baseline, load_config().evaluation)
    assert all_passed(outcomes)


def test_v2_is_blocked_by_regression_gate_on_fresh_set(repo_root: Path, mock_client, prompts) -> None:
    sets = _load_sets(repo_root, "regression.jsonl")
    baseline = evaluate_prompt(prompts["v1"], sets, mock_client, 0.7)
    candidate = evaluate_prompt(prompts["v2"], sets, mock_client, 0.7)
    outcomes = check_gates(candidate, baseline, load_config().evaluation)
    regression = next(outcome for outcome in outcomes if outcome.name == "regression_avg_drop")
    assert not regression.passed
    assert not all_passed(outcomes)
    # The failing cases must be exactly the long-tail pricing phrasings.
    worst = sorted(candidate["regression"].scores, key=lambda pair: pair[1])[:3]
    assert [case_id for case_id, _ in worst] == ["reg-005", "reg-006", "reg-007"]


def test_edge_gate_fails_when_fail_rate_exceeds_limit() -> None:
    from gray_release.config import EvaluationConfig
    from gray_release.evaluation.runner import SetStats

    results = {
        "regression": SetStats(name="regression", avg=0.8, min=0.5, fail_count=0, total=10),
        "edge": SetStats(name="edge", avg=0.5, min=0.0, fail_count=1, total=10),
        "new_feature": SetStats(name="new_feature", avg=0.9, min=0.7, fail_count=0, total=6),
    }
    baseline = {"regression": SetStats(name="regression", avg=0.8, min=0.5, fail_count=0, total=10)}
    config = EvaluationConfig()
    config.gates.edge_max_fail_rate = 0.05
    outcomes = check_gates(results, baseline, config)
    edge = next(outcome for outcome in outcomes if outcome.name == "edge_fail_rate")
    assert not edge.passed


def test_baseline_roundtrip(tmp_path: Path) -> None:
    from gray_release.evaluation.runner import SetStats

    results = {
        "regression": SetStats(name="regression", avg=0.755, min=0.1, fail_count=3, total=10),
        "edge": SetStats(name="edge", avg=1.0, min=1.0, fail_count=0, total=10),
    }
    path = tmp_path / "baseline.json"
    save_baseline(results, path)
    loaded = load_baseline(path)
    assert loaded["regression"].avg == 0.755
    assert loaded["edge"].fail_count == 0
    assert loaded["regression"].scores == []


def test_render_report_includes_all_sets(repo_root: Path, mock_client, prompts) -> None:
    sets = _load_sets(repo_root, "regression.jsonl")
    results = evaluate_prompt(prompts["v1"], sets, mock_client, 0.7)
    report = render_report(results, "title")
    assert "regression" in report and "edge" in report and "new_feature" in report


def test_load_test_set_rejects_missing_input(tmp_path: Path) -> None:
    import json

    import pytest

    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({"expected": {}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_test_set(path)
