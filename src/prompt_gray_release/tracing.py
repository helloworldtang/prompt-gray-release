"""OpenTelemetry 调用追踪导出（可选能力，零依赖默认关闭）。

安装 ``pip install prompt-gray-release[otel]`` 后，包一层 router/模型函数即可
把「渲染了哪个版本、是否命中灰度、模型返回了什么」导出为 OTel span：

::

    from prompt_gray_release.tracing import traced, traced_model

    router = traced(router)        # render() 发 span：key/version/percent
    model = traced_model(model)    # 模型调用发 span：prompt_key/version/响应长度

未安装 opentelemetry-api 时两个函数原样返回传入对象——显式安装才开启，
不做静默降级之外的任何魔法。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .router import GrayRouter, RenderedPrompt

ModelFn = Callable[[RenderedPrompt, dict[str, Any] | None], str]


def _otel_available() -> bool:
    try:
        import opentelemetry.trace  # noqa: F401
    except ImportError:
        return False
    return True


def traced(router: GrayRouter) -> GrayRouter:
    """包一层 GrayRouter：每次 render 发一个 span（prompt_key/version/percent）。"""
    if not _otel_available():
        return router

    from opentelemetry.trace import SpanKind, get_tracer

    tracer = get_tracer("prompt-gray-release")
    inner_render = router.render

    def render_with_span(
        key: str, variables: dict[str, Any] | None = None, **kwargs: Any
    ) -> RenderedPrompt:
        rendered = inner_render(key, variables, **kwargs)
        with tracer.start_as_current_span(f"prompt.render:{key}", kind=SpanKind.INTERNAL) as span:
            span.set_attribute("prompt_gray.key", key)
            span.set_attribute("prompt_gray.version", rendered.version)
            span.set_attribute("prompt_gray.percent", rendered.percent)
        return rendered

    router.render = render_with_span  # type: ignore[method-assign, assignment]
    return router


def traced_model(model_fn: ModelFn) -> ModelFn:
    """包一层模型调用函数：每次调用发一个 span（prompt_key/version/响应长度）。"""
    if not _otel_available():
        return model_fn

    from opentelemetry.trace import SpanKind, get_tracer

    tracer = get_tracer("prompt-gray-release")

    def model_with_span(rendered: RenderedPrompt, variables: dict[str, Any] | None = None) -> str:
        with tracer.start_as_current_span(
            f"prompt.model:{rendered.prompt_key}", kind=SpanKind.INTERNAL
        ) as span:
            span.set_attribute("prompt_gray.key", rendered.prompt_key)
            span.set_attribute("prompt_gray.version", rendered.version)
            response = model_fn(rendered, variables)
            span.set_attribute("prompt_gray.response_len", len(response))
        return response

    return model_with_span
