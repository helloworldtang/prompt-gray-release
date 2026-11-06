"""pytest 集成示例：用 cassette 的确定性假模型测下游逻辑（不用 fixture 也能写）。

这是"确定性重演"在测试里的日常用法——把线上的真实调用当回归靶子：

    pytest examples/test_with_cassette.py

配套的 traffic.jsonl 先由 examples/quickstart.py 生成（或任何 Recorder 落盘的线上流量）。
"""

from __future__ import annotations

from pathlib import Path

from prompt_gray_release import Cassette, PromptRegistry, Replayer

HERE = Path(__file__).parent
TRAFFIC = HERE / "traffic.jsonl"


def _cassette() -> Cassette:
    if not TRAFFIC.exists():
        # 先跑 quickstart 生成录制
        import subprocess
        import sys

        subprocess.run([sys.executable, str(HERE / "quickstart.py")], check=True, cwd=HERE)
    return Cassette.load(TRAFFIC)


def test_downstream_parser_with_deterministic_model():
    """下游解析逻辑回归：模型响应恒定，解析挂了就是你自己改坏的。"""
    registry = PromptRegistry.from_yaml(HERE / "prompts.yaml")
    fake_model = Replayer(_cassette(), strict=False).deterministic_model("support_reply", "v1")

    rendered = registry.get("support_reply", "v1").template
    response = fake_model(rendered, {"name": "李四", "topic": "退款"})
    # deterministic_model 永远返回录制时的响应——断言随跑随过，零 API 成本
    assert isinstance(response, str)


def test_registry_matches_cassette():
    """模板漂移检测：当前注册表重渲染必须与录制一致（prompt-gray check 的 Python 版）。"""
    registry = PromptRegistry.from_yaml(HERE / "prompts.yaml")
    results = Replayer(_cassette()).replay_registry(registry)
    mismatched = [r for r in results if not r.matches]
    drifted = [(r.record.prompt_key, r.record.version) for r in mismatched]
    assert not drifted, f"模板漂移: {drifted}"
