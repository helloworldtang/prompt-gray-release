"""异常体系：全部继承自 PromptGrayReleaseError，调用方可以一个 except 兜底。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gate import EvalReport


class PromptGrayReleaseError(Exception):
    """prompt-gray-release 所有异常的基类。"""


class PromptNotFoundError(PromptGrayReleaseError):
    """Prompt key 不存在。"""


class VersionNotFoundError(PromptGrayReleaseError):
    """Prompt 版本不存在。"""


class TemplateRenderError(PromptGrayReleaseError):
    """模板渲染失败（例如缺少变量）。"""


class RolloutStateError(PromptGrayReleaseError):
    """灰度状态非法（未设置 stable、percent 越界、无进行中的灰度等）。"""


class EvalGateBlocked(PromptGrayReleaseError):
    """评测门禁拦截：候选版本得分未达标。"""

    def __init__(self, report: EvalReport) -> None:
        self.report = report
        super().__init__(
            f"[{report.key}] 评测门禁拦截：{report.candidate}={report.candidate_score:.3f}"
            f" vs 基线 {report.baseline}={report.baseline_score:.3f}"
            f"（要求 >= +{report.min_improvement:.3f}）"
        )


class ReplayMissError(PromptGrayReleaseError):
    """重演时在录制文件中找不到对应调用。"""
