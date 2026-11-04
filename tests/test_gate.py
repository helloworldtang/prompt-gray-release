from __future__ import annotations

import pytest

from prompt_gray_release import EvalCase, EvalGate, EvalGateBlocked, VersionNotFoundError, exact_match


def make_cases():
    return [
        EvalCase({"text": "hello"}, "摘要（v1）：hello"),
        EvalCase({"text": "world"}, "摘要（v1）：world"),
    ]


def test_exact_match_builtin():
    assert exact_match("ok", "ok") == 1.0
    assert exact_match(" ok ", "ok") == 1.0
    assert exact_match("bad", "ok") == 0.0


def test_contains_builtin():
    from prompt_gray_release import contains

    assert contains("结果包含 ok 内容", "ok") == 1.0
    assert contains("没有", "ok") == 0.0


def test_equal_template_passes_without_min_improvement(registry):
    report = EvalGate(registry).evaluate("summary", "v1", "v1", make_cases())
    assert report.passed is True
    assert report.candidate_score == report.baseline_score == 1.0


def test_candidate_worse_is_blocked(registry):
    report = EvalGate(registry).evaluate("summary", "v2", "v1", make_cases())
    assert report.passed is False
    assert report.candidate_score == 0.0
    assert report.baseline_score == 1.0


def test_candidate_better_passes(registry):
    cases = [EvalCase({"text": "hello"}, "摘要（v2）：hello")]
    report = EvalGate(registry).evaluate("summary", "v2", "v1", cases)
    assert report.passed is True


def test_enforce_raises_with_report(registry):
    with pytest.raises(EvalGateBlocked) as excinfo:
        EvalGate(registry).enforce("summary", "v2", "v1", make_cases())
    assert excinfo.value.report.passed is False
    assert "拦截" in str(excinfo.value)


def test_enforce_passes_returns_report(registry):
    report = EvalGate(registry).enforce("summary", "v1", "v1", make_cases())
    assert report.passed is True


def test_min_improvement_blocks_equal(registry):
    report = EvalGate(registry).evaluate("summary", "v1", "v1", make_cases(), min_improvement=0.1)
    assert report.passed is False


def test_empty_cases_raise(registry):
    with pytest.raises(ValueError):
        EvalGate(registry).evaluate("summary", "v1", "v1", [])


def test_custom_evaluator(registry):
    report = EvalGate(registry).evaluate("summary", "v2", "v1", make_cases(), evaluator=lambda o, e: 0.5)
    assert report.candidate_score == 0.5
    assert report.passed is True


def test_evaluator_receives_output_then_expected(registry):
    seen = []

    def spy(output, expected):
        seen.append((output, expected))
        return 1.0

    EvalGate(registry).evaluate("summary", "v1", "v1", make_cases(), evaluator=spy)
    assert seen[0] == ("摘要（v1）：hello", "摘要（v1）：hello")


def test_case_results_populated(registry):
    report = EvalGate(registry).evaluate("summary", "v2", "v1", make_cases())
    assert len(report.cases) == 2
    assert report.cases[0].output == "摘要（v2）：hello"
    assert report.cases[0].baseline_output == "摘要（v1）：hello"


def test_candidate_version_missing_raises(registry):
    with pytest.raises(VersionNotFoundError):
        EvalGate(registry).evaluate("summary", "v99", "v1", make_cases())


def test_report_summary_string(registry):
    ok = EvalGate(registry).evaluate("summary", "v1", "v1", make_cases())
    bad = EvalGate(registry).evaluate("summary", "v2", "v1", make_cases())
    assert "通过" in ok.summary()
    assert "拦截" in bad.summary()
