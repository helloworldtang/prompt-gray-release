"""Prompt 注册表：key -> version -> 模板与元数据。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .exceptions import PromptNotFoundError, VersionNotFoundError


@dataclass(frozen=True)
class PromptVersion:
    """一个 Prompt 的某个版本。"""

    key: str
    version: str
    template: str
    metadata: dict[str, object] = field(default_factory=dict)


class PromptRegistry:
    """内存注册表，可从 YAML / JSON / dict 构造。

    YAML 结构::

        prompts:
          support_reply:
            v1:
              template: |
                你好 $name ...
              metadata:
                model: gpt-4o-mini
    """

    def __init__(self, prompts: dict[str, dict[str, dict[str, object]]] | None = None) -> None:
        self._prompts: dict[str, dict[str, PromptVersion]] = {}
        for key, versions in (prompts or {}).items():
            self._prompts[key] = {}
            for version, spec in (versions or {}).items():
                if not isinstance(spec, dict) or "template" not in spec:
                    raise ValueError(f"prompt {key}/{version} 缺少 template 字段")
                self._prompts[key][version] = PromptVersion(
                    key=key,
                    version=version,
                    template=cast("str", spec["template"]),
                    metadata=cast("dict[str, object]", spec.get("metadata") or {}),
                )

    @classmethod
    def from_yaml(cls, path: str | Path) -> PromptRegistry:
        import yaml  # 延迟导入：PyYAML 是本库唯一依赖

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(data.get("prompts", data))

    @classmethod
    def from_json(cls, path: str | Path) -> PromptRegistry:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("prompts", data))

    def get(self, key: str, version: str) -> PromptVersion:
        """严格获取指定版本；key 或 version 不存在时抛错。"""
        if key not in self._prompts:
            raise PromptNotFoundError(f"prompt 不存在: {key}")
        if version not in self._prompts[key]:
            raise VersionNotFoundError(
                f"prompt {key} 版本不存在: {version}（可用: {self.versions(key)}）"
            )
        return self._prompts[key][version]

    def versions(self, key: str) -> list[str]:
        """返回某 key 的全部版本（按定义顺序）。"""
        if key not in self._prompts:
            raise PromptNotFoundError(f"prompt 不存在: {key}")
        return list(self._prompts[key].keys())

    def latest(self, key: str) -> PromptVersion:
        """返回某 key 最新（定义顺序最后一个）的版本。"""
        return self.get(key, self.versions(key)[-1])

    def keys(self) -> list[str]:
        return list(self._prompts.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._prompts
