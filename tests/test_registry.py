from __future__ import annotations

import dataclasses
import json

import pytest

from prompt_gray_release import PromptNotFoundError, PromptRegistry, VersionNotFoundError


def test_keys_in_definition_order(registry):
    assert registry.keys() == ["support_reply", "summary"]


def test_get_template_and_metadata(registry):
    pv = registry.get("support_reply", "v1")
    assert pv.template == "你好 $name，这是 v1 的回复模板。"
    assert pv.metadata == {"model": "m1"}
    assert pv.key == "support_reply"
    assert pv.version == "v1"


def test_get_missing_key_raises(registry):
    with pytest.raises(PromptNotFoundError):
        registry.get("nope", "v1")


def test_get_missing_version_raises(registry):
    with pytest.raises(VersionNotFoundError):
        registry.get("support_reply", "v99")


def test_versions_in_definition_order(registry):
    assert registry.versions("support_reply") == ["v1", "v2", "v3"]


def test_latest_is_last_defined(registry):
    assert registry.latest("support_reply").version == "v3"
    assert registry.latest("summary").version == "v2"


def test_contains(registry):
    assert "support_reply" in registry
    assert "nope" not in registry


def test_metadata_defaults_to_empty(registry):
    assert registry.get("support_reply", "v3").metadata == {}


def test_missing_template_raises():
    with pytest.raises(ValueError):
        PromptRegistry({"k": {"v1": {"metadata": {"model": "m"}}}})


def test_from_yaml(tmp_path):
    p = tmp_path / "prompts.yaml"
    p.write_text(
        "prompts:\n"
        "  k1:\n"
        "    v1:\n"
        '      template: "你好 $name"\n'
        "      metadata:\n"
        "        model: m1\n",
        encoding="utf-8",
    )
    reg = PromptRegistry.from_yaml(p)
    assert reg.get("k1", "v1").template == "你好 $name"
    assert reg.get("k1", "v1").metadata == {"model": "m1"}


def test_from_yaml_without_prompts_key(tmp_path):
    p = tmp_path / "prompts.yaml"
    p.write_text("k1:\n  v1:\n    template: T\n", encoding="utf-8")
    reg = PromptRegistry.from_yaml(p)
    assert "k1" in reg


def test_from_json(tmp_path):
    p = tmp_path / "prompts.json"
    p.write_text(json.dumps({"prompts": {"k1": {"v1": {"template": "T"}}}}), encoding="utf-8")
    reg = PromptRegistry.from_json(p)
    assert reg.get("k1", "v1").template == "T"


def test_version_is_frozen(registry):
    pv = registry.get("summary", "v1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        pv.template = "改掉"


def test_empty_registry():
    assert PromptRegistry().keys() == []
