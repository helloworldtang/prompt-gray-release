"""Comparator scoring rules."""

from __future__ import annotations

import pytest

from gray_release.evaluation.comparator import score_response
from gray_release.intents import AnswerChecklist


def test_full_coverage_scores_one() -> None:
    checklist = AnswerChecklist(
        must_contain=("元", "2999"),
        must_not_contain=("无法回答",),
        keywords=("优惠", "退货"),
    )
    answer = "售价 2999 元，有优惠，支持退货。"
    assert score_response(answer, checklist) == 1.0


def test_empty_answer_scores_zero() -> None:
    checklist = AnswerChecklist(must_contain=("元",))
    assert score_response("   ", checklist) == 0.0


def test_forbidden_token_voids_score() -> None:
    checklist = AnswerChecklist(must_contain=("元",), must_not_contain=("无法回答",))
    assert score_response("抱歉，我无法回答价格问题。", checklist) == 0.0


def test_partial_coverage_weights() -> None:
    # 3/4 must-contain (0.45) + 2/3 keywords (0.20) + clean 0.10 = 0.75
    checklist = AnswerChecklist(
        must_contain=("元", "2999", "优惠", "会员"),
        keywords=("30天", "退货", "免费"),
    )
    answer = "售价 2999 元，近期有优惠，支持 30天内退货。"
    assert score_response(answer, checklist) == pytest.approx(0.75)


def test_missing_keyword_section_treated_as_full() -> None:
    checklist = AnswerChecklist(must_contain=("升降",))
    assert score_response("支持升降调节。", checklist) == pytest.approx(1.0)


def test_score_is_rounded_to_four_decimals() -> None:
    checklist = AnswerChecklist(must_contain=("a", "b", "c"), keywords=("x", "y", "z"))
    # 1/3 * 0.6 + 1/3 * 0.3 + 0.1 = 0.4 exactly after rounding
    assert score_response("a x", checklist) == 0.4
