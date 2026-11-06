from __future__ import annotations

import json

import pytest

from prompt_gray_release import Cassette, Recorder, Replayer, ReplayMissError
from prompt_gray_release.recorder import variables_fingerprint


@pytest.fixture()
def rendered(router):
    return router.render("summary", {"text": "hi"})


def test_record_writes_jsonl(tmp_path, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    lines = rec_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["prompt_key"] == "summary"
    assert data["version"] == "v1"
    assert data["rendered_text"] == "摘要（v1）：hi"
    assert data["response"] == "resp-1"
    assert set(data.keys()) == {
        "prompt_key",
        "version",
        "variables",
        "rendered_text",
        "response",
        "ts",
    }


def test_record_appends_multiple_lines(tmp_path, rendered):
    rec = Recorder(tmp_path / "traffic.jsonl")
    rec.record(rendered, {"text": "hi"}, "resp-1")
    rec.record(rendered, {"text": "hi2"}, "resp-2")
    assert len(tmp_path.joinpath("traffic.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_record_creates_parent_dirs(tmp_path):
    from prompt_gray_release import RenderedPrompt

    rp = RenderedPrompt(prompt_key="k", version="v1", text="t", metadata={}, percent=0)
    Recorder(tmp_path / "a" / "b" / "traffic.jsonl").record(rp, {}, "resp")
    assert (tmp_path / "a" / "b" / "traffic.jsonl").exists()


def test_wrap_returns_response_and_records(tmp_path, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    model = Recorder(rec_path).wrap(lambda text: f"模型回复：{text}")
    out = model(rendered, {"text": "hi"})
    assert out == "模型回复：摘要（v1）：hi"
    assert len(Cassette.load(rec_path)) == 1


def test_cassette_roundtrip(tmp_path, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    rec = Recorder(rec_path)
    rec.record(rendered, {"text": "hi"}, "resp-1")
    rec.record(rendered, {"text": "hi2"}, "resp-2")
    cassette = Cassette.load(rec_path)
    assert len(cassette) == 2


def test_lookup_hit_and_miss(tmp_path, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    cassette = Cassette.load(rec_path)
    assert cassette.lookup("summary", "v1", {"text": "hi"}).response == "resp-1"
    assert cassette.lookup("summary", "v1", {"text": "other"}) is None
    assert cassette.lookup("summary", "v9", {"text": "hi"}) is None


def test_fingerprint_order_insensitive():
    assert variables_fingerprint({"a": 1, "b": 2}) == variables_fingerprint({"b": 2, "a": 1})
    assert variables_fingerprint({"a": 1}) != variables_fingerprint({"a": 2})


def test_deterministic_model_returns_recorded_response(tmp_path, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    replayer = Replayer(Cassette.load(rec_path))
    model = replayer.deterministic_model("summary", "v1")
    assert model("任意文本", {"text": "hi"}) == "resp-1"
    assert model("任意文本", {"text": "hi"}) == "resp-1"  # 确定性：两次一致


def test_deterministic_model_strict_miss_raises(tmp_path, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    replayer = Replayer(Cassette.load(rec_path))
    with pytest.raises(ReplayMissError):
        replayer.deterministic_model("summary", "v1")("文本", {"text": "other"})


def test_deterministic_model_non_strict_returns_none(tmp_path, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    replayer = Replayer(Cassette.load(rec_path), strict=False)
    assert replayer.deterministic_model("summary", "v1")("文本", {"text": "other"}) is None


def test_replay_matches_when_template_unchanged(tmp_path, registry, rendered):
    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    results = Replayer(Cassette.load(rec_path)).replay_registry(registry)
    assert len(results) == 1
    assert results[0].matches is True
    assert results[0].rendered_now == "摘要（v1）：hi"


def test_replay_detects_template_drift(tmp_path, rendered):
    from prompt_gray_release import PromptRegistry

    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    drifted = PromptRegistry({"summary": {"v1": {"template": "摘要（v1·改版）：$text"}}})
    results = Replayer(Cassette.load(rec_path)).replay_registry(drifted)
    assert results[0].matches is False
    assert results[0].rendered_now == "摘要（v1·改版）：hi"


def test_replay_unknown_key_marks_not_match(tmp_path, rendered):
    from prompt_gray_release import PromptRegistry

    rec_path = tmp_path / "traffic.jsonl"
    Recorder(rec_path).record(rendered, {"text": "hi"}, "resp-1")
    empty = PromptRegistry({})
    results = Replayer(Cassette.load(rec_path)).replay_registry(empty)
    assert results[0].matches is False
    assert results[0].rendered_now is None
