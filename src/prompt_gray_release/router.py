"""灰度路由：按稳定 hash 把流量在 stable / candidate 之间分配。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .registry import PromptRegistry
from .render import render_template
from .rollout import RolloutController


def bucket(key: str, user_key: str) -> int:
    """稳定分桶：同一 (prompt, user) 永远落在同一桶，跨进程/重启不变。"""
    digest = hashlib.sha256(f"{key}#{user_key}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


@dataclass
class RenderedPrompt:
    """一次渲染结果：选中了哪个版本、渲染出的文本、携带的元数据。"""

    prompt_key: str
    version: str
    text: str
    metadata: dict[str, object]
    percent: int


class GrayRouter:
    """根据灰度状态决定每次请求用哪个版本。

    路由规则：

    - ``percent >= 100``：全部走 candidate；
    - ``0 < percent < 100`` 且提供 ``user_key``：按稳定 hash 分桶，前 ``percent`` 桶走 candidate；
    - ``user_key`` 缺失时不猜（非 100% 一律走 stable）——宁可不灰度，不可不确定；
    - 其余情况走 stable。
    """

    def __init__(self, registry: PromptRegistry, rollout: RolloutController) -> None:
        self.registry = registry
        self.rollout = rollout

    def route(self, key: str, user_key: str | None = None) -> tuple[str, int]:
        """返回 (选中的版本, 当前灰度百分比)。"""
        st = self.rollout.state(key)
        if st.candidate and st.percent >= 100:
            return st.candidate, st.percent
        if (
            st.candidate
            and 0 < st.percent < 100
            and user_key is not None
            and bucket(key, user_key) < st.percent
        ):
            return st.candidate, st.percent
        return st.stable, st.percent

    def render(
        self, key: str, variables: dict[str, str] | None = None, user_key: str | None = None
    ) -> RenderedPrompt:
        """路由并渲染。缺少变量时抛 TemplateRenderError（fail-fast）。"""
        version, percent = self.route(key, user_key=user_key)
        pv = self.registry.get(key, version)
        return RenderedPrompt(
            prompt_key=key,
            version=version,
            text=render_template(pv.template, variables),
            metadata=dict(pv.metadata),
            percent=percent,
        )
