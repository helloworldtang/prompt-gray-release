from __future__ import annotations

import json
import os

import pytest

from prompt_gray_release import RolloutController, RolloutStateError
from prompt_gray_release import rollout as rollout_module


def test_set_stable_creates_state():
    rc = RolloutController()
    rc.set_stable("k", "v1")
    st = rc.state("k")
    assert st.stable == "v1"
    assert st.candidate is None
    assert st.percent == 0


def test_state_without_stable_raises():
    rc = RolloutController()
    with pytest.raises(RolloutStateError):
        rc.state("k")


def test_start_rollout_defaults_to_zero_percent(rollout):
    rollout.start_rollout("support_reply", "v2")
    st = rollout.state("support_reply")
    assert st.candidate == "v2"
    assert st.percent == 0


def test_set_percent_updates(rollout):
    rollout.start_rollout("support_reply", "v2")
    rollout.set_percent("support_reply", 25)
    assert rollout.state("support_reply").percent == 25


def test_set_percent_without_rollout_raises(rollout):
    with pytest.raises(RolloutStateError):
        rollout.set_percent("support_reply", 25)


@pytest.mark.parametrize("bad", [101, -1, "50", 1.5, None, True])
def test_invalid_percent_raises(rollout, bad):
    rollout.start_rollout("support_reply", "v2")
    with pytest.raises(RolloutStateError):
        rollout.set_percent("support_reply", bad)


def test_candidate_equals_stable_raises(rollout):
    with pytest.raises(RolloutStateError):
        rollout.start_rollout("support_reply", "v1")


def test_second_rollout_with_different_candidate_raises(rollout):
    rollout.start_rollout("support_reply", "v2")
    with pytest.raises(RolloutStateError):
        rollout.start_rollout("support_reply", "v3")


def test_restart_same_candidate_updates_percent(rollout):
    rollout.start_rollout("support_reply", "v2", 10)
    rollout.start_rollout("support_reply", "v2", 30)
    assert rollout.state("support_reply").percent == 30


def test_promote_full(rollout):
    rollout.start_rollout("support_reply", "v2", 50)
    rollout.promote_full("support_reply")
    st = rollout.state("support_reply")
    assert st.stable == "v2"
    assert st.candidate is None
    assert st.percent == 0


def test_promote_full_without_rollout_raises(rollout):
    with pytest.raises(RolloutStateError):
        rollout.promote_full("support_reply")


def test_rollback_keeps_stable(rollout):
    rollout.start_rollout("support_reply", "v2", 50)
    rollout.rollback("support_reply")
    st = rollout.state("support_reply")
    assert st.stable == "v1"
    assert st.candidate is None
    assert st.percent == 0


def test_rollback_without_rollout_raises(rollout):
    with pytest.raises(RolloutStateError):
        rollout.rollback("support_reply")


def test_set_stable_to_candidate_equals_promote_full(rollout):
    rollout.start_rollout("support_reply", "v2", 30)
    rollout.set_stable("support_reply", "v2")
    st = rollout.state("support_reply")
    assert st.stable == "v2"
    assert st.candidate is None
    assert st.percent == 0


def test_persistence_roundtrip(tmp_path):
    p = tmp_path / "rollout.json"
    rc = RolloutController(state_path=p)
    rc.set_stable("k", "v1")
    rc.start_rollout("k", "v2", 40)
    rc2 = RolloutController(state_path=p)
    st = rc2.state("k")
    assert st.stable == "v1"
    assert st.candidate == "v2"
    assert st.percent == 40


def test_atomic_write_leaves_no_tmp_file(tmp_path):
    p = tmp_path / "rollout.json"
    rc = RolloutController(state_path=p)
    rc.set_stable("k", "v1")
    rc.start_rollout("k", "v2", 10)
    assert not (tmp_path / "rollout.json.tmp").exists()
    assert json.loads(p.read_text(encoding="utf-8"))["k"]["stable"] == "v1"


def test_audit_log_records_actions(tmp_path):
    p = tmp_path / "rollout.json"
    rc = RolloutController(state_path=p)
    rc.set_stable("k", "v1")
    rc.start_rollout("k", "v2", 10)
    rc.set_percent("k", 30)
    rc.promote_full("k")
    events = [
        json.loads(line)
        for line in (tmp_path / "rollout.json.events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    actions = [e["action"] for e in events]
    assert actions == ["set_stable", "start_rollout", "set_percent", "promote_full"]
    assert events[-1]["stable"] == "v2"


def test_no_audit_without_state_path():
    rc = RolloutController()
    rc.set_stable("k", "v1")
    assert rc.audit_path is None


# ---------- 热重载：外部修改（CLI / 另一进程 / ConfigMap）无需重启即可见 ----------


def test_external_change_visible_without_restart(tmp_path):
    p = tmp_path / "rollout.json"
    app = RolloutController(state_path=p)
    app.set_stable("k", "v1")
    app.start_rollout("k", "v2", 40)
    assert app.state("k").percent == 40

    cli = RolloutController(state_path=p)  # 模拟 CLI 进程
    cli.rollback("k")

    assert app.state("k").candidate is None  # 运行中的实例在下一次访问看到回滚
    assert app.state("k").percent == 0


def test_no_reread_when_file_unchanged(tmp_path, monkeypatch):
    p = tmp_path / "rollout.json"
    rc = RolloutController(state_path=p)
    rc.set_stable("k", "v1")

    calls = {"loads": 0}
    real_loads = json.loads

    def counting_loads(payload):
        calls["loads"] += 1
        return real_loads(payload)

    monkeypatch.setattr(rollout_module.json, "loads", counting_loads)
    rc.state("k")
    rc.has("k")
    assert calls["loads"] == 0  # 签名未变时不重读文件


def test_corrupt_state_file_fails_closed(tmp_path):
    p = tmp_path / "rollout.json"
    rc = RolloutController(state_path=p)
    rc.set_stable("k", "v1")

    p.write_text("{ not json", encoding="utf-8")
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 1_000_000))

    with pytest.raises(RolloutStateError, match="已损坏"):
        rc.state("k")


def test_deleted_state_file_keeps_memory_state(tmp_path):
    p = tmp_path / "rollout.json"
    rc = RolloutController(state_path=p)
    rc.set_stable("k", "v1")
    rc.start_rollout("k", "v2", 30)

    p.unlink()

    assert rc.state("k").percent == 30  # 文件消失不抛错，沿用内存状态


def test_write_after_external_change_does_not_clobber(tmp_path):
    p = tmp_path / "rollout.json"
    app = RolloutController(state_path=p)
    app.set_stable("k", "v1")
    app.start_rollout("k", "v2", 10)

    cli = RolloutController(state_path=p)  # 模拟 CLI 进程
    cli.set_percent("k", 50)

    app.set_percent("k", 80)  # 写前重读：基于 50 改到 80，而非把旧内存 10 写回
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["k"]["percent"] == 80


def test_write_sees_external_new_key(tmp_path):
    p = tmp_path / "rollout.json"
    app = RolloutController(state_path=p)
    app.set_stable("k", "v1")

    cli = RolloutController(state_path=p)  # 模拟 CLI 进程：给新 prompt 开灰度
    cli.set_stable("other", "v1")
    cli.start_rollout("other", "v2", 10)

    app.set_percent("other", 50)  # 无写前重读会抛"没有进行中的灰度"
    assert json.loads(p.read_text(encoding="utf-8"))["other"]["percent"] == 50
