"""prompt-gray-release: 把 Prompt 当生产代码发布。

版本化、灰度放量、评测门禁、一键回滚、事故确定性重演。
"""

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

__version__ = "0.1.0"

__all__ = [
    "__version__",
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
