"""多环境状态隔离：dev / staging / prod 各持独立状态文件与审计流。

用法::

    from prompt_gray_release import RolloutController

    prod = RolloutController.for_env("rollout", "prod")
    # state  -> rollout.prod.json
    # audit  -> rollout.prod.json.events.jsonl

dev 里放到 100% 不会影响 prod 的状态机——环境之间只有文件路径不同，
但路径不同就是状态不同（发布状态的隔离不需要更复杂的机制）。
"""

from __future__ import annotations

from pathlib import Path

VALID_ENVS = ("dev", "staging", "prod")


def state_path_for_env(base: str | Path, env: str) -> Path:
    """按环境推导状态文件路径：``rollout + prod -> rollout.prod.json``。"""
    if env not in VALID_ENVS:
        raise ValueError(f"env 只支持 {'/'.join(VALID_ENVS)}，收到: {env}")
    base_path = Path(base)
    stem = base_path.stem
    suffix = base_path.suffix or ".json"
    return base_path.with_name(f"{stem}.{env}{suffix}")
