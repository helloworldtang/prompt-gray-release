"""灰度状态机：stable / candidate / percent，支持持久化与审计。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

from .exceptions import RolloutStateError


@dataclass
class RolloutState:
    """单个 prompt 的灰度状态。

    - ``stable``：当前全量版本；
    - ``candidate``：灰度中的候选版本（无灰度时为 None）；
    - ``percent``：候选版本承接的流量百分比（0-100）。
    """

    stable: str
    candidate: Optional[str] = None
    percent: int = 0


class RolloutController:
    """管理所有 prompt 的灰度状态。

    传入 ``state_path`` 后，每次状态变更都会原子落盘，并追加 JSONL 审计事件
    （默认写到 ``<state_path>.events.jsonl``），满足"谁在什么时候把哪个版本放了多少流量"的可追溯要求。
    """

    def __init__(self, state_path=None, audit_path=None) -> None:
        self._states: Dict[str, RolloutState] = {}
        self.state_path = Path(state_path) if state_path else None
        if self.state_path is not None:
            self.audit_path = Path(audit_path) if audit_path else Path(str(self.state_path) + ".events.jsonl")
        else:
            self.audit_path = None
        if self.state_path is not None and self.state_path.exists():
            self._load()

    # ---------- 查询 ----------

    def state(self, key: str) -> RolloutState:
        """读取某 prompt 的灰度状态；未设置 stable 时抛错。"""
        if key not in self._states:
            raise RolloutStateError(f"prompt {key} 尚未设置 stable 版本（请先调用 set_stable）")
        return self._states[key]

    def has(self, key: str) -> bool:
        return key in self._states

    # ---------- 变更 ----------

    def set_stable(self, key: str, version: str) -> None:
        """设置/切换 stable 版本。若与进行中的 candidate 相同，等价于 promote_full。"""
        if not version:
            raise RolloutStateError("stable 版本不能为空")
        if key in self._states and self._states[key].candidate == version:
            self.promote_full(key)
            return
        if key in self._states:
            self._states[key].stable = version
        else:
            self._states[key] = RolloutState(stable=version)
        self._audit("set_stable", key)
        self._persist()

    def start_rollout(self, key: str, candidate: str, percent: int = 0) -> None:
        """开始灰度：指定候选版本与初始放量百分比。"""
        st = self.state(key)
        if candidate == st.stable:
            raise RolloutStateError(f"候选版本 {candidate} 与 stable 相同，无需灰度")
        if st.candidate and st.candidate != candidate:
            raise RolloutStateError(
                f"prompt {key} 已有进行中的灰度 {st.candidate}，请先 promote_full 或 rollback"
            )
        st.candidate = candidate
        if not isinstance(percent, int) or isinstance(percent, bool) or not 0 <= percent <= 100:
            raise RolloutStateError("percent 必须是 0-100 的整数")
        st.percent = percent
        self._audit("start_rollout", key)
        self._persist()

    def set_percent(self, key: str, percent: int) -> None:
        """调整候选版本承接的流量百分比（0-100 整数）。"""
        st = self.state(key)
        if not st.candidate:
            raise RolloutStateError(f"prompt {key} 没有进行中的灰度，无法调整流量")
        if not isinstance(percent, int) or isinstance(percent, bool) or not 0 <= percent <= 100:
            raise RolloutStateError("percent 必须是 0-100 的整数")
        st.percent = percent
        self._audit("set_percent", key)
        self._persist()

    def promote_full(self, key: str) -> None:
        """全量：candidate 升级为 stable。"""
        st = self.state(key)
        if not st.candidate:
            raise RolloutStateError(f"prompt {key} 没有进行中的灰度")
        st.stable = st.candidate
        st.candidate = None
        st.percent = 0
        self._audit("promote_full", key)
        self._persist()

    def rollback(self, key: str) -> None:
        """回滚：放弃 candidate，流量全部回到 stable。"""
        st = self.state(key)
        if not st.candidate:
            raise RolloutStateError(f"prompt {key} 没有进行中的灰度")
        st.candidate = None
        st.percent = 0
        self._audit("rollback", key)
        self._persist()

    # ---------- 持久化与审计 ----------

    def save(self) -> None:
        """显式落盘（状态变更时也会自动落盘）。"""
        self._persist()

    def _persist(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(st) for key, st in self._states.items()}
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _load(self) -> None:
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        for key, st in data.items():
            self._states[key] = RolloutState(
                stable=st["stable"], candidate=st.get("candidate"), percent=st.get("percent", 0)
            )

    def _audit(self, action: str, key: str) -> None:
        if self.audit_path is None:
            return
        st = self._states.get(key)
        event = {
            "ts": round(time.time(), 3),
            "action": action,
            "prompt_key": key,
            "stable": st.stable if st else None,
            "candidate": st.candidate if st else None,
            "percent": st.percent if st else None,
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
