# prompt-gray-release

**Ship prompts like production code.** A lightweight, embeddable, zero-platform
prompt release engineering library: versioning → eval gates → canary rollout →
one-click rollback → deterministic incident replay.

> [中文文档](README.md)

## Why this exists: the fundamental difference from platforms

LangSmith / Langfuse are **evaluation and observability platforms** — they tell you
whether things work, but they don't control **the moment of release**.
prompt-gray-release owns that moment, and it never asks you to build or migrate to
a platform:

| | LangSmith / Langfuse etc. | prompt-gray-release |
|---|---|---|
| Form factor | SaaS / self-hosted service; data leaves your domain or lands in their storage | **A pure library**; `pip install` and go, data never leaves your process |
| Privacy & audit | Self-hosting means running their whole stack | **JSONL audit events built in**, append-only, compliance-ready |
| CI gating | Depends on platform CI integrations | `prompt-gray check` runs natively locally & in CI; **template drift blocks the merge** |
| Incident replay | Dataset snapshots (re-calling the model) | **Deterministic replay**: responses recorded once, replayed forever at zero cost |
| Dependencies | Platform SDK + account + network | **Single dependency: PyYAML** |

In one sentence: **use the platforms to see how you're doing, use
prompt-gray-release to ship.** For teams without a platform, it works standalone.

## Goals

**Let any team put prompt changes under the same release discipline as code —
without building a platform.**

1. **Ship safely**: prompt changes pass an eval gate, roll out by traffic
   percentage, and roll back in seconds (Registry / EvalGate / RolloutController);
2. **Verify behavior**: every behavioral change is deterministically replayable
   and auto-detected (Recorder / Replayer / `prompt-gray check`);
3. **Audit everything**: who, when, which version, how much traffic — full JSONL
   traceability.

**Not goals**: model routing, an evaluation platform, a web console — this
project is only the release layer.

## Installation

```bash
pip install prompt-gray-release
```

Python >= 3.10. Single runtime dependency: PyYAML.

## Quick start

Runnable examples: [examples/quickstart.py](examples/quickstart.py) (no API key,
mock model) and [examples/openai_demo.py](examples/openai_demo.py) (real model,
any OpenAI-compatible endpoint).

### 1. Define prompt versions (prompts.yaml)

```yaml
prompts:
  support_reply:
    v1:
      template: |
        Hello $name, this is the v1 template. Your $topic question will be handled soon.
    v2:
      template: |
        Hi $name! Brand-new v2 template, specialized for $topic.
```

### 2. Canary routing: the same user always gets the same version

```python
from prompt_gray_release import GrayRouter, PromptRegistry, RolloutController

registry = PromptRegistry.from_yaml("prompts.yaml")
rollout = RolloutController()
rollout.set_stable("support_reply", "v1")
router = GrayRouter(registry, rollout)

rollout.start_rollout("support_reply", "v2", percent=10)  # 10% traffic first
r = router.render("support_reply", {"name": "Alice", "topic": "invoice"}, user_key="user-42")
print(r.version, "->", r.text)  # whichever bucket user-42 lands in, it stays there
```

Rules: `percent >= 100` sends everything to the candidate; `0 < percent < 100`
buckets by stable hash; **without a user_key it never guesses** — non-full
rollouts always go to stable (rather no canary than a nondeterministic one).

### 3. Eval gate: block candidates that don't clear the baseline

```python
from prompt_gray_release import EvalCase, EvalGate

gate = EvalGate(registry)
cases = [EvalCase({"name": "Alice", "topic": "invoice"}, "expected answer...")]
report = gate.evaluate("support_reply", candidate="v2", baseline="v1", cases=cases)
print(report.summary())

if report.passed:
    rollout.set_percent("support_reply", 50)  # only then ramp up
else:
    rollout.rollback("support_reply")         # roll back in seconds
```

Evaluators are pluggable: built-in `exact_match` / `contains`, plus factories
`regex` / `keywords` / `json_valid` / `json_schema`
(see [src/prompt_gray_release/evaluators.py](src/prompt_gray_release/evaluators.py)),
or any custom `evaluator(output, expected) -> float` — including a real model as
judge ([examples/openai_demo.py](examples/openai_demo.py)). `gate.enforce(...)`
raises `EvalGateBlocked` on failure (fail-closed) for CI use.

### 4. Ramp-up, rollback, audit

```python
rollout.set_percent("support_reply", 10)
rollout.set_percent("support_reply", 50)
rollout.promote_full("support_reply")   # candidate becomes stable
rollout.rollback("support_reply")       # or: back to stable in seconds
```

With `state_path`, every change is **atomically persisted** and appended to a
**JSONL audit event stream**. Environments are isolated by file:
`RolloutController.for_env("rollout", "prod")` → `rollout.prod.json`.

**Hot reload**: every state access first checks the file's signature
`(mtime_ns, size, ino)`. If the state file was modified externally — by the CLI,
another process, or a ConfigMap mount — running instances pick it up on their
next request. No restart, no redeploy: rollback propagation latency is one
request. A deleted file keeps the in-memory state; a corrupted one raises
(fail-closed).

### 5. Recording & deterministic replay

```python
from prompt_gray_release import Cassette, Recorder, Replayer

recorder = Recorder("traffic.jsonl")
model = recorder.wrap(real_model)  # every call is recorded (input + model response)

cassette = Cassette.load("traffic.jsonl")
for item in Replayer(cassette).replay_registry(registry):
    print(item.matches, item.rendered_now)  # False = template has drifted

fake_model = Replayer(cassette).deterministic_model("support_reply", "v2")
fake_model("anything", {"name": "Alice", "topic": "invoice"})  # always the recorded response
```

Why this matters: LLM output isn't reproducible, but once you record
"input + the response at the time", **the same inputs always yield the same
outputs** — your downstream parsing / routing / fallback logic finally has a
stable regression target; `matches=False` directly tells you "someone changed
the template after the incident".

## CLI: no Python required

```bash
prompt-gray set-stable      support_reply v1               --state rollout.json
prompt-gray start-rollout   support_reply v2 --percent 10  --state rollout.json
prompt-gray status          support_reply                  --state rollout.json
prompt-gray set-percent     support_reply 50               --state rollout.json
prompt-gray rollback        support_reply                  --state rollout.json
prompt-gray promote-full    support_reply                  --state rollout.json
```

All mutating commands go through the single write entry point with automatic
auditing.

## CI replay gate: change one line of a template, CI goes red

```bash
prompt-gray check --cassette traffic.jsonl --registry prompts.yaml --strict
```

```yaml
# .github/workflows/prompt-drift.yml
on: [pull_request]
jobs:
  prompt-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install prompt-gray-release
      - run: prompt-gray check --cassette traffic.jsonl --registry prompts.yaml --strict
```

**A PR that changes one line of a template gets blocked; reverting turns CI
green again.** The cassette travels with the repo — the gate behaves identically
locally and in CI, with no external service.

## Run with a real model in 5 minutes

```bash
pip install openai prompt-gray-release
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://...   # optional: any OpenAI-compatible endpoint
python examples/openai_demo.py
```

Covers: canary routing picks the candidate → real model call, recorded →
real-model-as-judge eval gate (auto-rollback on failure) → zero-cost
deterministic replay. The library itself never depends on `openai`.

## Integrations

- FastAPI: [examples/fastapi_app.py](examples/fastapi_app.py) — `router.render`
  inside a request handler, plus a `/__rollback` endpoint.
- Kubernetes: mount the state file from a ConfigMap — `prompt-gray rollback`
  against the mounted file reaches every pod on its next request, no
  `kubectl rollout restart` needed.
- pytest: [examples/test_with_cassette.py](examples/test_with_cassette.py) —
  deterministic fake models from cassettes for downstream-logic regression tests.
- OpenTelemetry (optional `[otel]` extra): wrap with `traced(router)` /
  `traced_model(model)` to export spans.

## Design principles

1. **A library, not a platform**: embeds into your existing code with one
   `pip install`;
2. **Fail-fast / fail-closed**: missing variables raise, failing evals block,
   replay misses raise — no silent defaults on the release path;
3. **Determinism first**: no random canary without user_key; replay uses
   recorded responses, never "ask the model again";
4. **Audit built in**: atomic persistence + JSONL event stream.

## Roadmap

See [TODO.md](TODO.md). Done: CLI. Next: more evaluator integrations.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests examples && ruff format --check src tests examples
mypy src  # strict
```

## License

[MIT](LICENSE) © helloworldtang
