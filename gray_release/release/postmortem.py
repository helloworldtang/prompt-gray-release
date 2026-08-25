"""Post-mortem generation after a breaker rollback (pit #4).

A rollback without analysis guarantees the same incident next release. This
module captures what the machine knows -- when it tripped, at what traffic
percentage, which condition, and the worst affected dialogues -- and leaves
root cause / prevention sections as explicit TODOs for the human.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from gray_release.release.canary import BreakerTrigger, RolloutOutcome
from gray_release.release.metrics import DialogueSample

POSTMORTEM_TEMPLATE = """# Post-mortem: prompt gray release rollback

- **Incident time**: {incident_time}
- **Traffic percentage at trip**: {percentage}%
- **Cooldown**: {cooldown_hours}h before the next release attempt

## Triggered conditions

{triggers}

## Affected dialogue samples (lowest satisfaction, new prompt)

{samples}

## Root cause

(TODO - fill in: which prompt change caused which behaviour, and why the
offline eval sets did not catch it.)

## Prevention

(TODO - fill in: eval-set additions, threshold changes, process fixes.)

## Reminder

Pit #1: refresh eval sets weekly from production logs (keep 80% old + 20%
new) so long-tail phrasings make it offline before they make it online.
"""


def _render_samples(samples: list[DialogueSample]) -> str:
    if not samples:
        return "(none recorded)"
    lines = []
    for sample in samples[:10]:
        lines.append(
            f"- user={sample.user_id} stars={sample.stars} [{sample.version_label}]\n"
            f"  - Q: {sample.message!r}\n"
            f"  - A: {sample.answer[:120]!r}"
        )
    return "\n".join(lines)


def _render_triggers(triggers: list[BreakerTrigger]) -> str:
    if not triggers:
        return "(none)"
    return "\n".join(f"- **{trigger.condition}**: {trigger.detail}" for trigger in triggers)


def render_postmortem(outcome: RolloutOutcome, samples: list[DialogueSample]) -> str:
    """Render the post-mortem markdown for a rolled-back release.

    Args:
        outcome: The rollout outcome (rolled_back must be True).
        samples: Worst dialogue samples captured during the rollout.

    Returns:
        Markdown text with machine-known facts filled in and human sections
        marked TODO.
    """
    trip_percentage = outcome.steps[-1].percentage if outcome.steps else 0
    return POSTMORTEM_TEMPLATE.format(
        incident_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        percentage=trip_percentage,
        cooldown_hours=outcome.cooldown_seconds // 3600,
        triggers=_render_triggers(outcome.triggers),
        samples=_render_samples(samples),
    )


def write_postmortem(outcome: RolloutOutcome, samples: list[DialogueSample], directory: Path) -> Path:
    """Write the post-mortem under the given directory and return its path.

    Args:
        outcome: Rolled-back rollout outcome.
        samples: Worst dialogue samples for the evidence section.
        directory: Output directory; created when missing.

    Returns:
        Path to the written markdown file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = directory / f"postmortem-{stamp}.md"
    path.write_text(render_postmortem(outcome, samples), encoding="utf-8")
    return path
