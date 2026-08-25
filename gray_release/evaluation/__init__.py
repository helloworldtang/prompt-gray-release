"""Layer 1: offline evaluation of prompt changes against curated test sets."""

from gray_release.evaluation.comparator import score_response
from gray_release.evaluation.datasets import EvalCase, load_test_set
from gray_release.evaluation.gates import GateOutcome, all_passed, check_gates
from gray_release.evaluation.runner import SetStats, evaluate_prompt, render_report
from gray_release.intents import AnswerChecklist

__all__ = [
    "AnswerChecklist",
    "EvalCase",
    "GateOutcome",
    "SetStats",
    "all_passed",
    "check_gates",
    "evaluate_prompt",
    "load_test_set",
    "render_report",
    "score_response",
]
