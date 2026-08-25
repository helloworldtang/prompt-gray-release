"""Prompt gray release toolkit.

Three layers of protection for AI prompt changes:

1. Offline evaluation gates (evaluation) -- regression / edge / new-feature
   test sets must pass before a prompt touches production traffic.
2. Small-percentage A/B test (release.ab_test) -- 1% traffic split, judged on
   satisfaction, task completion and response time.
3. Progressive rollout with automatic circuit breaker (release.canary) --
   5% -> 20% -> 50% -> 100%, tripping back to the last stable prompt when a
   windowed metric breaches its threshold.
"""

from gray_release.config import ReleaseConfig, load_config

__all__ = ["ReleaseConfig", "load_config"]
