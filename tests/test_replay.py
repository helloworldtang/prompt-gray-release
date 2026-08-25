"""Traffic replay: mix interleaving, group collection, clock."""

from __future__ import annotations

from gray_release.intents import Intent, classify_intent
from gray_release.replay import (
    AB_TEST_MIX,
    FakeClock,
    TrafficMix,
    collect_group_users,
    message_sequence,
)
from gray_release.traffic.router import ReleaseMode, TrafficPlan


def test_message_sequence_matches_mix_distribution() -> None:
    messages = message_sequence(200, TrafficMix(weights={Intent.PRICE_STANDARD: 0.6, Intent.PRICE_LONG_TAIL: 0.4}))
    long_tail = sum(1 for message in messages if classify_intent(message) is Intent.PRICE_LONG_TAIL)
    assert abs(long_tail / 200 - 0.4) <= 0.05


def test_message_sequence_interleaves_from_the_start() -> None:
    """Small samples must reflect the mix, not a single leading block."""
    messages = message_sequence(60, AB_TEST_MIX)
    intents = [classify_intent(message) for message in messages]
    long_tail_count = intents.count(Intent.PRICE_LONG_TAIL)
    assert long_tail_count >= 2  # 5% of 60, interleaved
    assert intents[0] is not intents[-1] or len(set(intents)) > 1


def test_message_sequence_is_deterministic() -> None:
    first = message_sequence(50, AB_TEST_MIX)
    second = message_sequence(50, AB_TEST_MIX)
    assert first == second


def test_collect_group_users_finds_exactly_the_group() -> None:
    plan = TrafficPlan(mode=ReleaseMode.AB, ab_a_permille=5, ab_b_permille=5)
    a_users = collect_group_users(plan, "A", 10)
    assert len(a_users) == 10
    assert all(plan.group_for(user) == "A" for user in a_users)


def test_fake_clock_advance() -> None:
    clock = FakeClock(start=100.0)
    assert clock() == 100.0
    clock.advance(0.5)
    assert clock() == 100.5
