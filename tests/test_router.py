"""Consistent-hash router: stability, exclusivity, monotonicity, proportion."""

from __future__ import annotations

import pytest

from gray_release.traffic.router import (
    PERMILLE,
    ReleaseMode,
    TrafficPlan,
    user_bucket,
)


def _users(count: int) -> list[str]:
    return [f"user-{index:06d}" for index in range(count)]


def test_bucket_is_deterministic_and_in_range() -> None:
    for user_id in _users(100):
        first = user_bucket(user_id)
        assert 0 <= first < PERMILLE
        assert user_bucket(user_id) == first


def test_same_user_always_same_group() -> None:
    plan = TrafficPlan(mode=ReleaseMode.AB, ab_a_permille=5, ab_b_permille=5)
    for user_id in _users(500):
        assert len({plan.group_for(user_id) for _ in range(5)}) == 1


def test_ab_groups_are_exclusive() -> None:
    """Pit #2: one user must never appear in both A and B."""
    plan = TrafficPlan(mode=ReleaseMode.AB, ab_a_permille=5, ab_b_permille=5)
    a_members = {user for user in _users(20_000) if plan.group_for(user) == "A"}
    b_members = {user for user in _users(20_000) if plan.group_for(user) == "B"}
    assert a_members & b_members == set()


def test_ramp_up_is_monotonic() -> None:
    """Pit #3 corollary: raising the percentage never demotes a treated user."""
    low = TrafficPlan(mode=ReleaseMode.ROLLOUT, treatment_permille=50)
    high = TrafficPlan(mode=ReleaseMode.ROLLOUT, treatment_permille=200)
    treated_at_low = {user for user in _users(5_000) if low.group_for(user) == "treatment"}
    treated_at_high = {user for user in _users(5_000) if high.group_for(user) == "treatment"}
    assert treated_at_low <= treated_at_high


def test_bucket_distribution_matches_percentage() -> None:
    users = _users(20_000)
    hits = sum(1 for user in users if user_bucket(user) < 100)  # 10%
    assert hits / len(users) == pytest.approx(0.10, abs=0.01)


def test_ab_split_sizes() -> None:
    plan = TrafficPlan(mode=ReleaseMode.AB, ab_a_permille=5, ab_b_permille=5)
    users = _users(20_000)
    a_count = sum(1 for user in users if plan.group_for(user) == "A")
    b_count = sum(1 for user in users if plan.group_for(user) == "B")
    assert a_count / len(users) == pytest.approx(0.005, abs=0.002)
    assert b_count / len(users) == pytest.approx(0.005, abs=0.002)


def test_version_labels_per_group() -> None:
    plan = TrafficPlan()
    assert plan.version_label_for("A") == "new"
    assert plan.version_label_for("treatment") == "new"
    assert plan.version_label_for("B") == "stable"
    assert plan.version_label_for("control") == "stable"
    with pytest.raises(ValueError):
        plan.version_label_for("ghost")


def test_full_mode_serves_everyone_the_new_prompt() -> None:
    plan = TrafficPlan(mode=ReleaseMode.FULL)
    assert all(plan.group_for(user) == "treatment" for user in _users(100))


def test_off_mode_serves_everyone_the_stable_prompt() -> None:
    plan = TrafficPlan(mode=ReleaseMode.OFF)
    assert all(plan.group_for(user) == "control" for user in _users(100))
