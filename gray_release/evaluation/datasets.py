"""JSONL test-set loading for the three offline eval sets.

Production sizes referenced in the runbook: regression 500 cases (real
historical dialogues), edge 200 cases (empty / oversized / gibberish /
injection), new-feature sized per change. The repo ships 10-case samples so
the pipeline runs end to end offline; refresh cadence lives in
config.release_config.yaml (keep 80% old + 20% new per week, pit #1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gray_release.intents import AnswerChecklist

REGRESSION_SET = "regression"
EDGE_SET = "edge"
NEW_FEATURE_SET = "new_feature"


@dataclass(frozen=True)
class EvalCase:
    """One offline evaluation case.

    Attributes:
        id: Stable case identifier, e.g. "reg-001".
        input: The user message exactly as captured.
        expected: Checklist the answer is graded against.
    """

    id: str
    input: str
    expected: AnswerChecklist


def parse_case(raw: dict[str, object], fallback_id: str) -> EvalCase:
    """Build an EvalCase from a parsed JSONL record.

    Args:
        raw: Record with "input" plus optional "id" and "expected" mapping.
        fallback_id: Used when the record carries no id.

    Returns:
        The assembled EvalCase.

    Raises:
        ValueError: If the record has no "input" field.
    """
    user_input = raw.get("input")
    if not isinstance(user_input, str):
        raise ValueError(f"eval case {fallback_id!r} is missing a string 'input' field")
    case_id = raw.get("id", fallback_id)
    expected_raw = raw.get("expected", {})
    if not isinstance(expected_raw, dict):
        raise ValueError(f"eval case {case_id!r}: 'expected' must be a mapping")
    expected = AnswerChecklist(
        must_contain=tuple(expected_raw.get("must_contain", ())),
        must_not_contain=tuple(expected_raw.get("must_not_contain", ())),
        keywords=tuple(expected_raw.get("keywords", ())),
    )
    return EvalCase(id=str(case_id), input=user_input, expected=expected)


def load_test_set(path: Path) -> list[EvalCase]:
    """Load a JSONL test set, one EvalCase per non-empty line.

    Args:
        path: Path to a .jsonl file.

    Returns:
        Cases in file order with ids "filename:lineno" fallbacks.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If any line is not valid JSON or lacks "input".
    """
    cases: list[EvalCase] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            cases.append(parse_case(raw, fallback_id=f"{path.stem}:{line_number}"))
    if not cases:
        raise ValueError(f"test set {path} contains no cases")
    return cases
