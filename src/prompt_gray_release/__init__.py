"""prompt-gray-release: 把 Prompt 当生产代码发布。

版本化、灰度放量、评测门禁、一键回滚、事故确定性重演。
"""

from .envs import state_path_for_env
from .evaluators import json_schema, json_valid, keywords, regex
from .exceptions import (
    EvalGateBlocked,
    PromptGrayReleaseError,
    PromptNotFoundError,
    ReplayMissError,
    RolloutStateError,
    TemplateRenderError,
    VersionNotFoundError,
)
from .gate import EvalCase, EvalGate, EvalReport, contains, exact_match
from .recorder import CallRecord, Cassette, Recorder, Replayer
from .registry import PromptRegistry, PromptVersion
from .render import render_template
from .rollout import RolloutController, RolloutState
from .router import GrayRouter, RenderedPrompt
from .tracing import traced, traced_model

__version__ = "0.4.0"


def __getattr__(name: str) -> object:
    # prompt_dep 懒加载：不在包导入时拉起 fastapi_dep 的类型链
    # （fastapi 本身到调用 prompt_dep 才要求安装）。
    if name == "prompt_dep":
        from .fastapi_dep import prompt_dep

        return prompt_dep
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    # fastapi 依赖注入（懒加载，可选 extra [fastapi]）
    "prompt_dep",
    # registry
    "PromptRegistry",
    "PromptVersion",
    # render
    "render_template",
    # rollout / router
    "RolloutController",
    "RolloutState",
    "GrayRouter",
    "RenderedPrompt",
    # gate
    "EvalGate",
    "EvalCase",
    "EvalReport",
    "exact_match",
    "contains",
    # evaluators
    "regex",
    "keywords",
    "json_valid",
    "json_schema",
    # envs / tracing
    "state_path_for_env",
    "traced",
    "traced_model",
    # recorder / replay
    "Recorder",
    "Cassette",
    "CallRecord",
    "Replayer",
    # exceptions
    "PromptGrayReleaseError",
    "PromptNotFoundError",
    "VersionNotFoundError",
    "TemplateRenderError",
    "RolloutStateError",
    "EvalGateBlocked",
    "ReplayMissError",
]
