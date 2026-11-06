"""录制与确定性重演：把线上真实调用录下来，之后随时原样重放。

确定性来自"回放录制的模型响应"——同一批输入永远得到同一批输出，
从而可以安全地验证：路由逻辑、模板改动、下游解析逻辑是否仍然正确。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .exceptions import ReplayMissError
from .registry import PromptRegistry
from .render import render_template
from .router import RenderedPrompt


def variables_fingerprint(variables: dict[str, object] | None) -> str:
    """变量指纹：同一组变量永远得到同一指纹（与键序无关）。"""
    payload = json.dumps(variables or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class CallRecord:
    """一次被录制下来的调用。"""

    prompt_key: str
    version: str
    variables: dict[str, Any]
    rendered_text: str
    response: str
    ts: float


class Recorder:
    """把 (渲染结果, 变量, 模型响应) 逐行追加到 JSONL 文件。

    典型用法::

        recorder = Recorder("traffic.jsonl")
        model = recorder.wrap(real_model)          # model(rendered) -> response
        response = model(router.render(key, vars)) # 调用即录制
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(
        self, rendered: RenderedPrompt, variables: dict[str, Any] | None, response: str
    ) -> CallRecord:
        rec = CallRecord(
            prompt_key=rendered.prompt_key,
            version=rendered.version,
            variables=dict(variables or {}),
            rendered_text=rendered.text,
            response=response,
            ts=round(time.time(), 3),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        return rec

    def wrap(self, model_fn: Callable[[str], str]) -> Callable[..., str]:
        """包一层模型调用：签名从 model(text) 变为 model(rendered, variables=None)，调用即录制。"""

        def wrapped(rendered: RenderedPrompt, variables: dict[str, Any] | None = None) -> str:
            response = model_fn(rendered.text)
            self.record(rendered, variables, response)
            return response

        return wrapped


class Cassette:
    """一卷"磁带"：一组录制记录，可按 (key, version, 变量指纹) 精确检索。"""

    def __init__(self, records: list[CallRecord]) -> None:
        self.records = records
        self._index: dict[tuple[str, str, str], CallRecord] = {
            (r.prompt_key, r.version, variables_fingerprint(r.variables)): r for r in records
        }

    @classmethod
    def load(cls, path: str | Path) -> Cassette:
        records: list[CallRecord] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(CallRecord(**json.loads(line)))
        return cls(records)

    def lookup(
        self, prompt_key: str, version: str, variables: dict[str, Any] | None
    ) -> CallRecord | None:
        return self._index.get((prompt_key, version, variables_fingerprint(variables)))

    def __len__(self) -> int:
        return len(self.records)


@dataclass
class ReplayResult:
    """单条重演结果：当时的响应（确定性），以及当前模板重新渲染的文本是否与当时一致。"""

    record: CallRecord
    rendered_now: str | None
    response: str
    matches: bool


class Replayer:
    """重演器。两种用法：

    1. ``replay_registry(registry)``：把录制集中的每条调用，用当前注册表重新渲染，
       对比模板是否被改动（matches=False 说明 Prompt 行为可能已漂移）；
    2. ``deterministic_model(...)``：返回一个"假模型"，永远返回当时录制的响应——
       用于确定性地测试下游解析 / 路由 / 降级逻辑。
    """

    def __init__(self, cassette: Cassette, strict: bool = True) -> None:
        self.cassette = cassette
        self.strict = strict

    def response_for(
        self, prompt_key: str, version: str, variables: dict[str, Any] | None
    ) -> str | None:
        """取录制的响应；strict 模式下找不到即抛 ReplayMissError。"""
        rec = self.cassette.lookup(prompt_key, version, variables)
        if rec is None:
            if self.strict:
                raise ReplayMissError(
                    f"录制中找不到调用: {prompt_key}/{version} {variables_fingerprint(variables)}"
                )
            return None
        return rec.response

    def deterministic_model(self, prompt_key: str, version: str) -> Callable[..., str | None]:
        """返回确定性的假模型：model(text, variables) -> 当时的响应。"""

        def model(text: str, variables: dict[str, Any] | None = None) -> str | None:
            return self.response_for(prompt_key, version, variables)

        return model

    def replay_registry(self, registry: PromptRegistry) -> list[ReplayResult]:
        """逐条重演：当前注册表重新渲染 vs 当时录制文本。"""
        results: list[ReplayResult] = []
        for rec in self.cassette.records:
            if rec.prompt_key not in registry or rec.version not in registry.versions(
                rec.prompt_key
            ):
                results.append(
                    ReplayResult(
                        record=rec, rendered_now=None, response=rec.response, matches=False
                    )
                )
                continue
            pv = registry.get(rec.prompt_key, rec.version)
            rendered_now = render_template(pv.template, rec.variables)
            results.append(
                ReplayResult(
                    record=rec,
                    rendered_now=rendered_now,
                    response=rec.response,
                    matches=(rendered_now == rec.rendered_text),
                )
            )
        return results
