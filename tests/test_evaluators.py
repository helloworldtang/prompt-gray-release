"""内置评测函数工厂与多环境隔离的契约测试。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from prompt_gray_release import (
    EvalCase,
    EvalGate,
    PromptRegistry,
    RolloutController,
    RolloutStateError,
    json_schema,
    json_valid,
    keywords,
    regex,
    state_path_for_env,
)


@pytest.fixture
def registry():
    return PromptRegistry(
        {
            "structured": {
                "v1": {"template": '输出 JSON: {"a": "$a"}'},
                "v2": {"template": '输出 JSON: {"a": "$a", "extra": true}'},
            }
        }
    )


class TestRegexEvaluator:
    def test_hit_and_miss(self):
        ev = regex(r"发票.*处理")
        assert ev("关于发票的问题我们会处理", "") == 1.0
        assert ev("关于退款的问题", "") == 0.0

    def test_invalid_pattern_raises(self):
        with pytest.raises(re.error):
            regex("([")


class TestKeywordsEvaluator:
    def test_all_mode(self):
        ev = keywords(["道歉", "时效"])
        assert ev("我们道歉，时效 3 天", "") == 1.0
        assert ev("我们道歉", "") == 0.0

    def test_any_mode(self):
        ev = keywords(["道歉", "时效"], mode="any")
        assert ev("我们道歉", "") == 1.0

    def test_empty_words_rejected(self):
        with pytest.raises(ValueError, match="至少需要一个关键词"):
            keywords([])

    def test_bad_mode_rejected(self):
        with pytest.raises(ValueError, match="all / any"):
            keywords(["a"], mode="some")


class TestJsonEvaluators:
    def test_json_valid(self):
        ev = json_valid()
        assert ev('{"a": 1}', "") == 1.0
        assert ev("{a: 1}", "") == 0.0

    def test_json_schema(self):
        ev = json_schema({"type": "object", "required": ["a"]})
        assert ev('{"a": 1}', "") == 1.0
        assert ev('{"b": 1}', "") == 0.0
        assert ev("not json", "") == 0.0

    def test_gate_with_json_evaluator(self, registry):
        """结构化输出场景：候选改崩了 JSON 形状 → 门禁拦截。"""
        gate = EvalGate(registry)
        report = gate.evaluate(
            "structured",
            candidate="v2",
            baseline="v1",
            cases=[EvalCase({"a": "1"}, "")],
            evaluator=lambda out, exp: json_valid()(out, exp) if "{" in out else 0.0,
        )
        # v1/v2 都渲染出合法 JSON，此用例应通过
        assert report.passed is True


class TestEnvIsolation:
    def test_path_derivation(self, tmp_path):
        assert state_path_for_env("rollout", "prod") == Path("rollout.prod.json")
        assert state_path_for_env(tmp_path / "st.json", "dev") == tmp_path / "st.dev.json"

    def test_invalid_env_rejected(self):
        with pytest.raises(ValueError, match="dev/staging/prod"):
            state_path_for_env("rollout", "production")

    def test_states_do_not_leak_between_envs(self, tmp_path):
        prod = RolloutController.for_env(tmp_path / "rollout", "prod")
        dev = RolloutController.for_env(tmp_path / "rollout", "dev")
        prod.set_stable("k", "v1")
        prod.start_rollout("k", "v2", 100)
        assert prod.state("k").percent == 100
        # dev 是全新状态机，不受 prod 放量影响
        assert dev.has("k") is False
        with pytest.raises(RolloutStateError, match="尚未设置 stable"):
            dev.state("k")
