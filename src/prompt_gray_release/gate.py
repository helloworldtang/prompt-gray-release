"""评测门禁：候选 Prompt 必须先跑过 golden 评测集、不输给基线，才允许放量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .exceptions import EvalGateBlocked
from .registry import PromptRegistry
from .render import render_template


def exact_match(output: str, expected: str) -> float:
    """完全匹配（忽略首尾空白）：1.0 / 0.0。"""
    return 1.0 if output.strip() == expected.strip() else 0.0


def contains(output: str, expected: str) -> float:
    """包含判断：期望内容出现在输出中即 1.0。"""
    return 1.0 if expected in output else 0.0


@dataclass(frozen=True)
class EvalCase:
    """一条评测样例：渲染变量 + 期望内容。"""

    variables: Dict[str, str]
    expected: str


@dataclass
class CaseResult:
    variables: Dict[str, str]
    output: str
    baseline_output: str
    score: float
    baseline_score: float


@dataclass
class EvalReport:
    """一次评测门禁的完整报告。"""

    key: str
    candidate: str
    baseline: str
    candidate_score: float
    baseline_score: float
    min_improvement: float
    passed: bool
    cases: List[CaseResult] = field(default_factory=list)

    def summary(self) -> str:
        verdict = "通过" if self.passed else "拦截"
        return "[{}] {}={:.3f} vs 基线 {}={:.3f}（要求 >= +{:.3f}）→ {}".format(
            self.key,
            self.candidate,
            self.candidate_score,
            self.baseline,
            self.baseline_score,
            self.min_improvement,
            verdict,
        )


class EvalGate:
    """对 candidate / baseline 两个版本跑同一份评测集，按均分比较。"""

    def __init__(self, registry: PromptRegistry) -> None:
        self.registry = registry

    def evaluate(
        self,
        key: str,
        candidate: str,
        baseline: str,
        cases: List[EvalCase],
        evaluator: Optional[Callable[[str, str], float]] = None,
        min_improvement: float = 0.0,
    ) -> EvalReport:
        """跑评测。``evaluator(output, expected) -> float``，默认完全匹配。

        ``min_improvement=0.0`` 表示不回归即可通过（不低于基线）；设为正数可要求必须提升。
        """
        if not cases:
            raise ValueError("评测集不能为空")
        evaluator = evaluator or exact_match

        results: List[CaseResult] = []
        candidate_scores: List[float] = []
        baseline_scores: List[float] = []
        for case in cases:
            candidate_pv = self.registry.get(key, candidate)
            baseline_pv = self.registry.get(key, baseline)
            output = render_template(candidate_pv.template, case.variables)
            baseline_output = render_template(baseline_pv.template, case.variables)
            score = float(evaluator(output, case.expected))
            baseline_score = float(evaluator(baseline_output, case.expected))
            results.append(
                CaseResult(
                    variables=dict(case.variables),
                    output=output,
                    baseline_output=baseline_output,
                    score=score,
                    baseline_score=baseline_score,
                )
            )
            candidate_scores.append(score)
            baseline_scores.append(baseline_score)

        candidate_avg = sum(candidate_scores) / len(candidate_scores)
        baseline_avg = sum(baseline_scores) / len(baseline_scores)
        passed = candidate_avg >= baseline_avg + min_improvement
        return EvalReport(
            key=key,
            candidate=candidate,
            baseline=baseline,
            candidate_score=candidate_avg,
            baseline_score=baseline_avg,
            min_improvement=min_improvement,
            passed=passed,
            cases=results,
        )

    def enforce(
        self,
        key: str,
        candidate: str,
        baseline: str,
        cases: List[EvalCase],
        evaluator: Optional[Callable[[str, str], float]] = None,
        min_improvement: float = 0.0,
    ) -> EvalReport:
        """评测并在不达标时直接抛出 :class:`EvalGateBlocked`（fail-closed）。"""
        report = self.evaluate(key, candidate, baseline, cases, evaluator, min_improvement)
        if not report.passed:
            raise EvalGateBlocked(report)
        return report
