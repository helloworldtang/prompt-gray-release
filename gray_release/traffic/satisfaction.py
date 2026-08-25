"""Online satisfaction simulation derived from checklist coverage.

Production feeds these numbers from real signals: end-of-dialogue star
ratings, task-completion events (order placed / issue resolved) and manual
sampling of ~100 dialogues per day. The checklist-based simulator stands in
for those signals offline so the demo replays the incident end to end --
it grades the same expectations the offline evaluator uses.
"""

from __future__ import annotations

from gray_release.evaluation.comparator import score_response
from gray_release.intents import CHECKLISTS, classify_intent


def score_to_stars(score: float) -> int:
    """Map a checklist score to the 1-5 star scale users would give.

    Args:
        score: Coverage score in [0, 1].

    Returns:
        5 stars for >= 0.85, 4 for >= 0.70, 3 for >= 0.50, 2 for >= 0.30,
        otherwise 1.
    """
    if score >= 0.85:
        return 5
    if score >= 0.70:
        return 4
    if score >= 0.50:
        return 3
    if score >= 0.30:
        return 2
    return 1


def simulate_satisfaction(user_message: str, answer: str) -> tuple[int, float]:
    """Derive (stars, score) a user would give for this answer.

    Args:
        user_message: The user's raw message (used to look up the checklist).
        answer: The answer shown under whichever prompt version served it.

    Returns:
        Tuple of (stars in 1-5, underlying checklist score in [0, 1]).
    """
    intent = classify_intent(user_message)
    score = score_response(answer, CHECKLISTS[intent])
    return score_to_stars(score), score


def is_completed(stars: int) -> bool:
    """A dialogue counts as task-completed at 4 stars or above.

    Args:
        stars: Satisfaction stars in 1-5.

    Returns:
        True when the user plausibly reached their goal (e.g. ordered or
        resolved the issue).
    """
    return stars >= 4
