from __future__ import annotations

import pytest

from prompt_gray_release import TemplateRenderError, render_template


def test_basic_substitution():
    assert render_template("你好 $name", {"name": "唐"}) == "你好 唐"


def test_brace_form():
    assert render_template("你好 ${name}！", {"name": "唐"}) == "你好 唐！"


def test_missing_var_raises_template_error():
    with pytest.raises(TemplateRenderError):
        render_template("你好 $name", {})


def test_json_braces_preserved():
    template = '输出 JSON：{"answer": "$answer", "note": {"k": 1}}'
    assert (
        render_template(template, {"answer": "ok"})
        == '输出 JSON：{"answer": "ok", "note": {"k": 1}}'
    )


def test_none_variables_keeps_static_template():
    assert render_template("纯文本模板，没有变量。", None) == "纯文本模板，没有变量。"


def test_dollar_escape():
    assert render_template("价格 $$name", {"name": "x"}) == "价格 $name"


def test_unicode_values():
    assert render_template("$a-$b", {"a": "λ", "b": "微"}) == "λ-微"


def test_repeated_variable():
    assert render_template("$x-$x-$x", {"x": "z"}) == "z-z-z"
