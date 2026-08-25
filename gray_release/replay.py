"""Deterministic production-like traffic replay.

Supplies the demo and the gateway warm-up CLI with reproducible traffic:
intent mixes are fixed weights, message variants rotate by index and user
ids are sequential, so every run of the demo replays the incident with
identical numbers (no RNG anywhere).
"""

from __future__ import annotations

from dataclasses import dataclass

from gray_release.intents import SAMPLE_MESSAGES, Intent
from gray_release.traffic.gateway import GatewayState, handle_chat
from gray_release.traffic.router import TrafficPlan

AB_TEST_DIALOGUES = 60
ROLLOUT_DIALOGUES_PER_STEP = 200


class FakeClock:
    """Deterministic injectable clock for compressing observation windows."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        """Create a clock frozen at the given epoch seconds.

        Args:
            start: Initial epoch time.
        """
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward; usable directly as a sleep_fn."""
        self._now += seconds


@dataclass(frozen=True)
class TrafficMix:
    """Intent distribution of synthetic traffic.

    Attributes:
        weights: Relative weight per intent; expanded into 100-ish slots.
    """

    weights: dict[Intent, float]


# What the A/B traffic looked like: direct phrasings dominate, long-tail
# pricing barely shows up in a small sample -- which is exactly how the A/B
# verdict came out positive in the incident.
AB_TEST_MIX = TrafficMix(
    weights={
        Intent.PRICE_STANDARD: 0.60,
        Intent.PRICE_LONG_TAIL: 0.05,
        Intent.NEW_FEATURE: 0.15,
        Intent.FEATURE: 0.20,
    }
)

# What production traffic actually looks like: real users phrase pricing
# questions in a hundred ways, and long-tail phrasings dominate.
PRODUCTION_MIX = TrafficMix(
    weights={
        Intent.PRICE_STANDARD: 0.40,
        Intent.PRICE_LONG_TAIL: 0.35,
        Intent.NEW_FEATURE: 0.05,
        Intent.FEATURE: 0.15,
        Intent.POLICY: 0.05,
    }
)


def message_sequence(count: int, mix: TrafficMix) -> list[str]:
    """Build a deterministic message list following a mix.

    Intents are interleaved by cumulative weight (Bresenham-style) rather
    than blocked, so even a 60-dialogue A/B sample already reflects the mix
    -- a block-ordered sequence would hand the first N dialogues to a single
    intent and skew any small-window measurement.

    Args:
        count: Number of messages to produce.
        mix: Intent distribution.

    Returns:
        Messages whose intent distribution matches the mix, with variants
        rotating deterministically per intent.
    """
    total_weight = sum(mix.weights.values())
    variants_used: dict[Intent, int] = {}
    messages: list[str] = []
    for index in range(count):
        position = (index + 0.5) * total_weight / count
        cumulative = 0.0
        chosen: Intent | None = None
        for intent, weight in mix.weights.items():
            cumulative += weight
            if position < cumulative:
                chosen = intent
                break
        if chosen is None:  # float round-off guard
            chosen = next(reversed(mix.weights))
        used = variants_used.get(chosen, 0)
        variants_used[chosen] = used + 1
        variants = SAMPLE_MESSAGES[chosen]
        messages.append(variants[used % len(variants)])
    return messages


def collect_group_users(plan: TrafficPlan, group: str, needed: int, max_scan: int = 200_000) -> list[str]:
    """Scan sequential user ids until enough users of one group are found.

    Args:
        plan: Traffic plan deciding group membership.
        group: Target group ("A" / "B" / "treatment" / "control").
        needed: How many users to collect.
        max_scan: Upper bound on ids examined.

    Returns:
        User ids belonging to the group, in scan order.
    """
    users: list[str] = []
    for index in range(max_scan):
        user_id = f"user-{index:06d}"
        if plan.group_for(user_id) == group:
            users.append(user_id)
            if len(users) >= needed:
                break
    return users


def replay_chats(state: GatewayState, user_ids: list[str], messages: list[str]) -> int:
    """Serve (user, message) pairs through the gateway chat core.

    Args:
        state: Gateway state; its current plan decides version routing.
        user_ids: One id per dialogue.
        messages: One message per dialogue.

    Returns:
        Number of dialogues served (min of both lengths).
    """
    served = 0
    for user_id, message in zip(user_ids, messages, strict=False):
        handle_chat(state, user_id, message)
        served += 1
    return served
