"""Consistent-hash traffic allocation.

Why md5 of the user id instead of a random split (pit #2): the hash is
deterministic, so one user always lands in the same group -- no leaking a
single user into both A and B, and no flip-flopping between groups when the
plan advances.

Why a single bucket per user makes ramp-up monotonic (pit #3): a user is in
the treatment group iff ``bucket < treatment_permille``, so raising the
percentage only ever *adds* users; nobody who already saw the new prompt is
sent back to the old one mid-release.
"""

from __future__ import annotations

import hashlib
from enum import Enum

PERMILLE = 1000


class ReleaseMode(str, Enum):
    """What the gateway is currently doing with traffic."""

    OFF = "off"  # everything on the stable prompt (post-rollback state)
    AB = "ab"  # layer 2: A = new on 0.5%, B = old on 0.5%
    ROLLOUT = "rollout"  # layer 3: new on treatment_permille, rest stable
    FULL = "full"  # new prompt at 100%


NEW_VERSION = "new"
STABLE_VERSION = "stable"

_TREATMENT_GROUPS = frozenset({"A", "treatment"})
_CONTROL_GROUPS = frozenset({"B", "control"})


def user_bucket(user_id: str) -> int:
    """Map a user id to a stable bucket in [0, PERMILLE).

    Args:
        user_id: Stable per-user identifier (session id, uid, ...).

    Returns:
        The user's bucket; identical inputs always return the same value.
    """
    digest = hashlib.md5(user_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % PERMILLE


class TrafficPlan:
    """Traffic allocation for the current release phase.

    Attributes:
        mode: Which phase is active (off / ab / rollout / full).
        ab_a_permille: A-group (new prompt) size in per-mille, AB mode only.
        ab_b_permille: B-group (old prompt) size in per-mille, AB mode only.
        treatment_permille: New-prompt size in per-mille, rollout mode only.
    """

    def __init__(
        self,
        mode: ReleaseMode = ReleaseMode.OFF,
        ab_a_permille: int = 5,
        ab_b_permille: int = 5,
        treatment_permille: int = 0,
    ) -> None:
        """Create a traffic plan.

        Args:
            mode: Release phase to activate.
            ab_a_permille: A-group size (per-mille) for AB mode.
            ab_b_permille: B-group size (per-mille) for AB mode.
            treatment_permille: Treatment size (per-mille) for rollout mode.
        """
        self.mode = mode
        self.ab_a_permille = ab_a_permille
        self.ab_b_permille = ab_b_permille
        self.treatment_permille = treatment_permille

    def group_for(self, user_id: str) -> str:
        """Assign a user to exactly one group under this plan.

        Args:
            user_id: Stable user identifier.

        Returns:
            "A" (new prompt, AB), "B" (old prompt, AB), "treatment" (new
            prompt, rollout/full) or "control" (old prompt). A user can only
            ever be in one group -- see module docstring on leak prevention.
        """
        bucket = user_bucket(user_id)
        if self.mode is ReleaseMode.AB:
            if bucket < self.ab_a_permille:
                return "A"
            if bucket < self.ab_a_permille + self.ab_b_permille:
                return "B"
            return "control"
        if self.mode is ReleaseMode.ROLLOUT:
            return "treatment" if bucket < self.treatment_permille else "control"
        if self.mode is ReleaseMode.FULL:
            return "treatment"
        return "control"

    def version_label_for(self, group: str) -> str:
        """Map an assigned group to the prompt version label it serves.

        Args:
            group: One of "A" / "B" / "treatment" / "control".

        Returns:
            "new" for A and treatment, "stable" for B and control.

        Raises:
            ValueError: For an unknown group name.
        """
        if group in _TREATMENT_GROUPS:
            return NEW_VERSION
        if group in _CONTROL_GROUPS:
            return STABLE_VERSION
        raise ValueError(f"unknown traffic group: {group!r}")

    def summary(self) -> str:
        """One-line human-readable description of the plan."""
        if self.mode is ReleaseMode.AB:
            return f"AB test: A(new)={self.ab_a_permille / 10}%, B(old)={self.ab_b_permille / 10}%"
        if self.mode is ReleaseMode.ROLLOUT:
            return f"rollout: new={self.treatment_permille / 10}%, old={100 - self.treatment_permille / 10:.1f}%"
        if self.mode is ReleaseMode.FULL:
            return "full: new=100%"
        return "off: stable=100%"
