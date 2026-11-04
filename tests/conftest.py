from __future__ import annotations

import pytest

from prompt_gray_release import PromptRegistry, RolloutController

PROMPTS = {
    "support_reply": {
        "v1": {"template": "你好 $name，这是 v1 的回复模板。", "metadata": {"model": "m1"}},
        "v2": {"template": "你好 $name，这是 v2 的回复模板，针对 $topic。", "metadata": {"model": "m2"}},
        "v3": {"template": "尊敬的 $name：关于 $topic 的问题，v3 已收到。"},
    },
    "summary": {
        "v1": {"template": "摘要（v1）：$text"},
        "v2": {"template": "摘要（v2）：$text"},
    },
}


@pytest.fixture()
def registry():
    return PromptRegistry(PROMPTS)


@pytest.fixture()
def rollout():
    rc = RolloutController()
    rc.set_stable("support_reply", "v1")
    rc.set_stable("summary", "v1")
    return rc


@pytest.fixture()
def router(registry, rollout):
    from prompt_gray_release import GrayRouter

    return GrayRouter(registry, rollout)
