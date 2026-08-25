"""LLM client abstraction with a deterministic mock implementation.

MockLLMClient reproduces the mechanics of the real incident:

* The v2 prompt answers *standard* pricing questions better than v1 (which is
  why the offline eval on the stale set looked fine).
* On *long-tail* pricing phrasings ("贵不贵", "有什么优惠") v2 drifts into a
  feature pitch and never states the price -- exactly the production failure
  that cost 15% conversion.
* Neither version regresses on edge cases (injection / gibberish / oversized).

Swap in any client implementing LLMClient for production; the rest of the
pipeline never touches the concrete class.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from gray_release.intents import Intent

VERSION_MARKER = re.compile(r"^#\s*version:\s*(\S+)", re.MULTILINE)

# Answer templates keyed by (prompt_version, intent). The exact wording is
# calibrated so checklist coverage yields the intended score; tests in
# tests/test_llm_mock.py lock the calibration in.
MOCK_ANSWERS: dict[tuple[str, Intent], str] = {
    (
        "v1",
        Intent.PRICE_STANDARD,
    ): "AeroDesk Pro 售价 2999 元，近期有以旧换新优惠。桌面支持电动升降、坐站记忆和儿童安全锁，30天内可无理由退货。请问您还想了解哪方面？",
    (
        "v1",
        Intent.PRICE_LONG_TAIL,
    ): "AeroDesk Pro 售价 2999 元，近期有以旧换新优惠。桌面支持电动升降、坐站记忆和儿童安全锁，30天内可无理由退货。请问您还想了解哪方面？",
    (
        "v1",
        Intent.FEATURE,
    ): "这款桌子支持电动升降、坐站记忆和儿童安全锁，升降过程很稳。30天内可无理由退货。请问您想了解哪个功能？",
    ("v1", Intent.POLICY): "支持 30天无理由退货，退换运费由我们承担，您放心下单。请问还有其他问题吗？",
    (
        "v1",
        Intent.NEW_FEATURE,
    ): "目前资料里没有提到赠品，具体以商品页为准。桌子本身支持电动升降和坐站记忆。请问您要看一下参数吗？",
    (
        "v2",
        Intent.PRICE_STANDARD,
    ): "AeroDesk Pro 售价 2999 元，会员价 2699 元，叠加限时优惠。现在下单还赠送线缆管理套装，30天无理由退货。请问您今天需要下单吗？",
    (
        "v2",
        Intent.PRICE_LONG_TAIL,
    ): "这款桌子的核心卖点是电动升降、坐站记忆预设和儿童安全锁，用料和做工都对得起定价。您更看重哪个功能呢？",
    (
        "v2",
        Intent.FEATURE,
    ): "核心卖点有三个：电动升降、坐站记忆预设，以及新增的安全锁设计。现在下单还赠送线缆管理套装。请问您想先了解哪个？",
    ("v2", Intent.POLICY): "支持 30天无理由退货，退换运费由我们承担，您放心下单。请问还有其他问题吗？",
    (
        "v2",
        Intent.NEW_FEATURE,
    ): "现在下单就赠送全新的线缆管理套装，免费加赠安装工具包，活动期内都有效。请问您需要我帮您下单吗？",
}

_EDGE_ANSWERS = {
    Intent.EMPTY: "您好，请问您想了解产品的哪方面？比如价格或者功能，我都可以介绍。",
    Intent.GIBBERISH: "抱歉，我没听清您的问题，麻烦您再说一遍或者换个说法。",
    Intent.INJECTION: "抱歉，我无法执行与产品咨询无关的指令。请问您有 AeroDesk Pro 相关的问题吗？",
    Intent.OVERSIZED: "您的消息有点长，我先确认一下：您是想了解桌子的功能对吧？它支持电动升降和坐站记忆。",
}
for _intent in _EDGE_ANSWERS:
    MOCK_ANSWERS[("v1", _intent)] = _EDGE_ANSWERS[_intent]
    MOCK_ANSWERS[("v2", _intent)] = _EDGE_ANSWERS[_intent]


@dataclass(frozen=True)
class LLMResponse:
    """A completed LLM call.

    Attributes:
        text: The answer shown to the user.
        response_time: Wall-clock seconds spent on the call.
    """

    text: str
    response_time: float


class LLMClient(Protocol):
    """Minimal chat-completion interface the pipeline depends on."""

    def complete(self, prompt: str, user_input: str) -> LLMResponse:
        """Answer user_input under the behaviour defined by prompt."""
        ...


def prompt_version(prompt: str) -> str:
    """Extract the ``# version: vX`` marker from a prompt file.

    Args:
        prompt: Full prompt text; the first matching marker line wins.

    Returns:
        The version token, e.g. "v1".

    Raises:
        ValueError: If the prompt carries no version marker.
    """
    match = VERSION_MARKER.search(prompt)
    if match is None:
        raise ValueError("prompt file must contain a '# version: vX' marker line")
    return match.group(1)


class MockLLMClient:
    """Deterministic mock used by tests, the demo and local traffic replay.

    Response time is slightly lower for v2 (shorter prompt), so the incident
    is never about latency -- it is purely an answer-quality regression on
    long-tail phrasings.
    """

    def complete(self, prompt: str, user_input: str) -> LLMResponse:
        """Return the calibrated answer for (prompt version, user intent).

        Args:
            prompt: Full prompt text with a version marker.
            user_input: Raw user message.

        Returns:
            The canned LLMResponse for that version/intent pair.

        Raises:
            ValueError: If the prompt has no version marker.
            KeyError: If no template exists for the pair (should not happen).
        """
        from gray_release.intents import classify_intent  # local import avoids a cycle at import time

        version = prompt_version(prompt)
        intent = classify_intent(user_input)
        template = MOCK_ANSWERS[(version, intent)]
        base_latency = 0.80 if version == "v1" else 0.60
        jitter = (len(user_input) % 5) * 0.02
        return LLMResponse(text=template, response_time=round(base_latency + jitter, 3))
