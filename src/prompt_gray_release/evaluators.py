"""内置评测函数工厂：正则 / JSON / 关键词集合，返回 ``(output, expected) -> float``。

用法（配合 :class:`prompt_gray_release.EvalGate`）::

    from prompt_gray_release.evaluators import json_valid, keywords, regex

    gate.evaluate(..., evaluator=regex(r"发票.*处理"))
    gate.evaluate(..., evaluator=keywords(["道歉", "时效"], mode="all"))
    gate.evaluate(..., evaluator=json_valid())      # 输出必须是合法 JSON

约定：所有评测函数返回 ``[0, 1]`` 浮点，不抛业务异常（输入非法按 0 分计，
fail-closed 的语义留给门禁本身）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable

Evaluator = Callable[[str, str], float]


def regex(pattern: str) -> Evaluator:
    """输出匹配正则得 1 分（expected 参数此时无用，传 "" 即可）。"""
    compiled = re.compile(pattern)

    def evaluate(output: str, expected: str) -> float:
        return 1.0 if compiled.search(output) else 0.0

    return evaluate


def keywords(words: Iterable[str], mode: str = "all") -> Evaluator:
    """关键词集合：``mode="all"`` 全部出现得 1 分，``"any"`` 任一出现得 1 分。"""
    word_list = list(words)
    if not word_list:
        raise ValueError("keywords 评测至少需要一个关键词")
    if mode not in ("all", "any"):
        raise ValueError(f"mode 只支持 all / any，收到: {mode}")

    def evaluate(output: str, expected: str) -> float:
        hits = sum(1 for w in word_list if w in output)
        if mode == "all":
            return 1.0 if hits == len(word_list) else 0.0
        return 1.0 if hits else 0.0

    return evaluate


def json_valid() -> Evaluator:
    """输出必须是合法 JSON（对结构化输出场景：格式崩坏直接 0 分）。"""

    def evaluate(output: str, expected: str) -> float:
        try:
            json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return 0.0
        return 1.0

    return evaluate


def json_schema(schema: dict[str, object]) -> Evaluator:
    """输出解析为 JSON 且符合 JSON Schema 得 1 分。

    需要可选依赖 ``jsonschema``（``pip install prompt-gray-release[schema]``），
    未安装时抛错而不是默默放行——门禁链路上不做静默降级。
    """
    try:
        from jsonschema import validate
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise ImportError(
            "json_schema 评测需要 jsonschema：pip install prompt-gray-release[schema]"
        ) from exc

    def evaluate(output: str, expected: str) -> float:
        from jsonschema.exceptions import ValidationError

        try:
            validate(instance=json.loads(output), schema=schema)
        except (json.JSONDecodeError, ValueError, ValidationError):
            return 0.0
        return 1.0

    return evaluate
