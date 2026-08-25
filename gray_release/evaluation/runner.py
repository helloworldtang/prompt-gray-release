"""Run a prompt over test sets and aggregate scores (evaluate_prompt).

Also provides baseline persistence: run once with the stable prompt to
produce baseline.json, then every candidate is judged against it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from gray_release.evaluation.comparator import score_response
from gray_release.evaluation.datasets import EvalCase
from gray_release.llm import LLMClient

SET_ORDER = ("regression", "edge", "new_feature")


@dataclass
class SetStats:
    """Aggregated scores for one test set.

    Attributes:
        name: Set name ("regression" / "edge" / "new_feature").
        avg: Mean score across cases.
        min: Worst single-case score.
        fail_count: Cases scoring below the fail threshold.
        total: Number of cases evaluated.
        scores: Per-case (id, score) pairs, kept for post-mortem digging.
    """

    name: str
    avg: float
    min: float
    fail_count: int
    total: int
    scores: list[tuple[str, float]] = field(default_factory=list)


def evaluate_set(
    prompt: str,
    set_name: str,
    cases: list[EvalCase],
    client: LLMClient,
    fail_threshold: float,
) -> SetStats:
    """Score one test set under a prompt.

    Args:
        prompt: Candidate prompt text.
        set_name: Name used in reports and gates.
        cases: Eval cases for this set.
        client: LLM backend answering each case input.
        fail_threshold: Scores below this count as failures.

    Returns:
        Aggregated SetStats for the set.
    """
    scored: list[tuple[str, float]] = []
    for case in cases:
        response = client.complete(prompt, case.input)
        score = score_response(response.text, case.expected)
        scored.append((case.id, score))
    values = [score for _, score in scored]
    return SetStats(
        name=set_name,
        avg=round(sum(values) / len(values), 4) if values else 0.0,
        min=min(values) if values else 0.0,
        fail_count=sum(1 for score in values if score < fail_threshold),
        total=len(values),
        scores=scored,
    )


def evaluate_prompt(
    prompt: str,
    test_sets: dict[str, list[EvalCase]],
    client: LLMClient,
    fail_threshold: float,
) -> dict[str, SetStats]:
    """Evaluate a prompt across all test sets.

    Args:
        prompt: Candidate prompt text.
        test_sets: Cases keyed by set name (regression / edge / new_feature).
        client: LLM backend.
        fail_threshold: Per-case failure line.

    Returns:
        SetStats keyed by set name.
    """
    return {name: evaluate_set(prompt, name, cases, client, fail_threshold) for name, cases in test_sets.items()}


def render_report(results: dict[str, SetStats], title: str) -> str:
    """Render eval results as an aligned plain-text table.

    Args:
        results: SetStats keyed by set name.
        title: Header line for the report.

    Returns:
        Multi-line report string.
    """
    lines = [title, "-" * 64, f"{'set':<14}{'avg':>8}{'min':>8}{'failed':>8}{'total':>8}"]
    for name in SET_ORDER:
        if name not in results:
            continue
        stats = results[name]
        lines.append(f"{stats.name:<14}{stats.avg:>8.3f}{stats.min:>8.3f}{stats.fail_count:>8}{stats.total:>8}")
    return "\n".join(lines)


def save_baseline(results: dict[str, SetStats], path: Path) -> None:
    """Persist baseline stats (scores dropped) as JSON.

    Args:
        results: SetStats keyed by set name, produced from the stable prompt.
        path: Destination file.
    """
    payload = {name: {k: v for k, v in asdict(stats).items() if k != "scores"} for name, stats in results.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict[str, SetStats]:
    """Load baseline stats previously written by save_baseline.

    Args:
        path: Baseline JSON file.

    Returns:
        SetStats keyed by set name (scores empty).

    Raises:
        FileNotFoundError: If path does not exist.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: SetStats(**stats) for name, stats in raw.items()}
