"""CLI 契约测试：exit code 与输出是给 CI / 运维用的 wire 接口，逐条断言。"""

from __future__ import annotations

import json

import pytest

from prompt_gray_release.cli import EXIT_GATE_FAILED, EXIT_OK, EXIT_USAGE, main
from prompt_gray_release.recorder import Recorder


@pytest.fixture
def registry_yaml(tmp_path):
    path = tmp_path / "prompts.yaml"
    path.write_text(
        """
prompts:
  support_reply:
    v1:
      template: "你好 $name，v1 模板。"
    v2:
      template: "你好 $name！v2 全新模板。"
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "rollout.json"


@pytest.fixture
def cassette_file(tmp_path, registry_yaml):
    """录制一条 v1 调用（与当前注册表一致）。"""
    from prompt_gray_release.router import RenderedPrompt

    rec_path = tmp_path / "traffic.jsonl"
    recorder = Recorder(rec_path)

    rendered = RenderedPrompt(
        prompt_key="support_reply",
        version="v1",
        text="你好 张三，v1 模板。",
        metadata={},
        percent=100,
    )
    recorder.record(rendered, {"name": "张三"}, "resp-1")
    return rec_path


class TestCheckGate:
    def test_all_match_exits_zero(self, capsys, cassette_file, registry_yaml):
        rc = main(["check", "--cassette", str(cassette_file), "--registry", str(registry_yaml)])
        out = capsys.readouterr().out
        assert rc == EXIT_OK
        assert "门禁通过" in out

    def test_template_drift_exits_one_with_detail(self, capsys, tmp_path, cassette_file):
        """改一行模板 → 门禁拦截（CI 变红的核心场景）。"""
        drifted = tmp_path / "drifted.yaml"
        drifted.write_text(
            """
prompts:
  support_reply:
    v1:
      template: "你好 $name，v1 模板（被偷偷改过）。"
    v2:
      template: "你好 $name！v2 全新模板。"
""",
            encoding="utf-8",
        )
        rc = main(["check", "--cassette", str(cassette_file), "--registry", str(drifted)])
        out = capsys.readouterr().out
        assert rc == EXIT_GATE_FAILED
        assert "模板漂移" in out
        assert "门禁拦截" in out

    def test_version_missing_exits_one(self, capsys, tmp_path, cassette_file):
        gone = tmp_path / "gone.yaml"
        gone.write_text(
            """
prompts:
  support_reply:
    v2:
      template: "你好 $name！v2 全新模板。"
""",
            encoding="utf-8",
        )
        rc = main(["check", "--cassette", str(cassette_file), "--registry", str(gone)])
        out = capsys.readouterr().out
        assert rc == EXIT_GATE_FAILED
        assert "版本缺失" in out

    def test_render_error_exits_one(self, capsys, tmp_path, cassette_file):
        """模板改到需要新变量 → 当时的变量渲染不了，也算漂移。"""
        broken = tmp_path / "broken.yaml"
        broken.write_text(
            """
prompts:
  support_reply:
    v1:
      template: "你好 $name，$tone 模板。"
    v2:
      template: "你好 $name！v2 全新模板。"
""",
            encoding="utf-8",
        )
        rc = main(["check", "--cassette", str(cassette_file), "--registry", str(broken)])
        out = capsys.readouterr().out
        assert rc == EXIT_GATE_FAILED
        assert "渲染失败" in out

    def test_strict_empty_cassette_fails(self, capsys, tmp_path, registry_yaml):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        rc = main(
            [
                "check",
                "--cassette",
                str(empty),
                "--registry",
                str(registry_yaml),
                "--strict",
            ]
        )
        assert rc == EXIT_GATE_FAILED
        assert "fail-closed" in capsys.readouterr().err

    def test_non_strict_empty_cassette_passes(self, capsys, tmp_path, registry_yaml):
        """非严格时空带子不拦（兼容刚起步、还没开始录制的仓库）。"""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        rc = main(["check", "--cassette", str(empty), "--registry", str(registry_yaml)])
        assert rc == EXIT_OK

    def test_multiple_cassettes(self, capsys, tmp_path, cassette_file, registry_yaml):
        second = tmp_path / "traffic2.jsonl"
        second.hardlink_to(cassette_file)
        rc = main(
            [
                "check",
                "--cassette",
                str(cassette_file),
                "--cassette",
                str(second),
                "--registry",
                str(registry_yaml),
            ]
        )
        out = capsys.readouterr().out
        assert rc == EXIT_OK
        assert "重演 2 条" in out


class TestOpsCommands:
    def test_full_rollout_lifecycle_with_audit(self, capsys, state_path, registry_yaml):
        """不写一行 Python 完成灰度+回滚，全程有审计。"""
        assert main(["set-stable", "support_reply", "v1", "--state", str(state_path)]) == EXIT_OK
        rc = main(
            [
                "start-rollout",
                "support_reply",
                "v2",
                "--percent",
                "10",
                "--state",
                str(state_path),
            ]
        )
        assert rc == EXIT_OK
        assert main(["set-percent", "support_reply", "50", "--state", str(state_path)]) == EXIT_OK
        assert main(["rollback", "support_reply", "--state", str(state_path)]) == EXIT_OK

        out = capsys.readouterr().out
        assert "开始灰度" in out and "已回滚" in out

        audit = state_path.parent / (state_path.name + ".events.jsonl")
        events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
        assert [e["action"] for e in events] == [
            "set_stable",
            "start_rollout",
            "set_percent",
            "rollback",
        ]

    def test_status_shows_rollout(self, capsys, state_path):
        main(["set-stable", "k", "v1", "--state", str(state_path)])
        main(["start-rollout", "k", "v2", "--percent", "10", "--state", str(state_path)])
        assert main(["status", "k", "--state", str(state_path)]) == EXIT_OK
        out = capsys.readouterr().out
        assert "stable=v1" in out and "candidate=v2" in out and "percent=10%" in out

    def test_bad_state_error_exits_two(self, capsys, state_path):
        rc = main(["set-percent", "k", "50", "--state", str(state_path)])
        assert rc == EXIT_USAGE
        assert "尚未设置 stable" in capsys.readouterr().err

    def test_promote_full(self, capsys, state_path):
        main(["set-stable", "k", "v1", "--state", str(state_path)])
        main(["start-rollout", "k", "v2", "--percent", "50", "--state", str(state_path)])
        assert main(["promote-full", "k", "--state", str(state_path)]) == EXIT_OK
        assert main(["status", "k", "--state", str(state_path)]) == EXIT_OK
        assert "stable=v2" in capsys.readouterr().out
