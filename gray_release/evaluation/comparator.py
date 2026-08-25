"""Score a single answer against its checklist.

Scoring model (weights chosen so the calibrated mock answers land on the
values the demo narrative relies on; see tests/test_comparator.py):

* must_contain coverage -- 60% weight
* keywords coverage     -- 30% weight
* cleanliness (no forbidden token, non-empty answer) -- 10% weight
"""

from __future__ import annotations

from gray_release.intents import AnswerChecklist

MUST_CONTAIN_WEIGHT = 0.6
KEYWORDS_WEIGHT = 0.3
CLEAN_WEIGHT = 0.1


def _coverage(answer: str, tokens: tuple[str, ...]) -> float:
    if not tokens:
        return 1.0
    hits = sum(1 for token in tokens if token in answer)
    return hits / len(tokens)


def score_response(response: str, expected: AnswerChecklist) -> float:
    """Score an answer in [0, 1] against a checklist.

    Args:
        response: The answer text produced under the candidate prompt.
        expected: Checklist of must_contain / must_not_contain / keywords.

    Returns:
        Weighted coverage score. An empty answer or any forbidden token
        present yields a near-floor score.
    """
    answer = response.strip()
    if not answer:
        return 0.0
    if any(token in answer for token in expected.must_not_contain):
        return 0.0
    score = (
        MUST_CONTAIN_WEIGHT * _coverage(answer, expected.must_contain)
        + KEYWORDS_WEIGHT * _coverage(answer, expected.keywords)
        + CLEAN_WEIGHT
    )
    return round(score, 4)
