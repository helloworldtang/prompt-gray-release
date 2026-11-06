"""模板渲染：$var / ${var} 语法（string.Template）。

选用 $ 语法的原因：LLM Prompt 里经常内嵌 JSON 示例，花括号不应被当作占位符。
"""

from __future__ import annotations

from string import Template

from .exceptions import TemplateRenderError


def render_template(template: str, variables: dict[str, str] | None = None) -> str:
    """渲染 Prompt 模板。

    - ``$name`` / ``${name}`` 会被替换为 variables 中的值；
    - ``$$`` 转义为字面量 ``$``；
    - 花括号 ``{}`` 原样保留（JSON 示例不受影响）；
    - 缺少变量时抛出 :class:`TemplateRenderError`（fail-fast，避免静默上线半成品 Prompt）。
    """
    try:
        return Template(template).substitute(**(variables or {}))
    except KeyError as exc:
        missing = exc.args[0]
        raise TemplateRenderError(f"模板缺少变量 ${missing}，请检查 variables 或模板") from exc
