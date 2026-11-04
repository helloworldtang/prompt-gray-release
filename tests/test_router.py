from __future__ import annotations

import pytest

from prompt_gray_release import RolloutStateError, TemplateRenderError
from prompt_gray_release.router import bucket


def test_zero_percent_serves_stable(registry, rollout, router):
    assert router.route("support_reply", "u1") == ("v1", 0)


def test_full_percent_serves_candidate(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 100)
    assert router.route("support_reply") == ("v2", 100)
    assert router.route("support_reply", "u1") == ("v2", 100)


def test_sticky_same_user_same_version(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 50)
    versions = {router.route("support_reply", "user-42")[0] for _ in range(50)}
    assert len(versions) == 1


def test_distribution_approximates_percent(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 25)
    hits = sum(1 for i in range(1000) if router.route("support_reply", f"u{i}")[0] == "v2")
    assert 200 <= hits <= 300


def test_one_percent_hits_few_users(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 1)
    hits = sum(1 for i in range(500) if router.route("support_reply", f"u{i}")[0] == "v2")
    assert 1 <= hits <= 15


def test_partial_percent_without_user_key_serves_stable(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 50)
    assert router.route("support_reply") == ("v1", 50)


def test_unknown_key_raises(registry, router):
    with pytest.raises(RolloutStateError):
        router.route("nope", "u1")


def test_render_fields(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 100)
    r = router.render("support_reply", {"name": "唐", "topic": "发票"}, user_key="u1")
    assert r.prompt_key == "support_reply"
    assert r.version == "v2"
    assert "唐" in r.text
    assert "发票" in r.text
    assert r.metadata == {"model": "m2"}
    assert r.percent == 100


def test_render_uses_stable_template(registry, rollout, router):
    r = router.render("support_reply", {"name": "唐"})
    assert "v1 的回复模板" in r.text
    assert r.version == "v1"


def test_rollback_returns_traffic_to_stable(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 100)
    rollout.rollback("support_reply")
    assert router.route("support_reply", "u1") == ("v1", 0)


def test_promote_full_switches_stable(registry, rollout, router):
    rollout.start_rollout("support_reply", "v2", 10)
    rollout.promote_full("support_reply")
    assert router.route("support_reply", "u1") == ("v2", 0)


def test_bucket_is_deterministic_and_bounded():
    assert bucket("k", "u") == bucket("k", "u")
    assert all(0 <= bucket("k", f"u{i}") <= 99 for i in range(200))


def test_prompts_have_independent_states(registry, rollout, router):
    rollout.start_rollout("summary", "v2", 100)
    assert router.route("support_reply", "u1") == ("v1", 0)
    assert router.route("summary", "u1") == ("v2", 100)


def test_render_missing_variable_raises(registry, rollout, router):
    with pytest.raises(TemplateRenderError):
        router.render("summary")
