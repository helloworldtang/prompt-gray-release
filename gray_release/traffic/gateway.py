"""Chat gateway: routes each request through the active TrafficPlan.

This is the single place where a user meets a prompt version. The demo and
tests call handle_chat() directly; production wraps it in the FastAPI app
exposed by create_app() with /chat, /metrics and /release endpoints.

Thread-safety note: the plan is swapped by attribute assignment, which is
atomic in CPython -- good enough for the single-replica demo and its ops
console. Wire a proper store (Redis/etcd) before running multi-replica
traffic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Response
from prometheus_client import CollectorRegistry
from pydantic import BaseModel, Field

from gray_release.llm import LLMClient, prompt_version
from gray_release.release.metrics import (
    CompositeRecorder,
    InMemoryMetricsStore,
    MetricsRecorder,
    PrometheusMetrics,
)
from gray_release.traffic.router import NEW_VERSION, STABLE_VERSION, ReleaseMode, TrafficPlan
from gray_release.traffic.satisfaction import is_completed, simulate_satisfaction


@dataclass
class GatewayState:
    """Everything the chat path needs; shared by demo, tests and FastAPI.

    Attributes:
        plan: Current traffic plan; swapped atomically on release updates.
        prompts: Prompt text keyed by version label ("new" / "stable").
        version_names: Prompt version marker per label, e.g. "v2"/"v1".
        client: LLM backend.
        recorder: Metrics sink (in-memory or Prometheus).
        prometheus: Optional Prometheus exposition; also drives the rollout
            percentage gauge shown in Grafana.
        stats: The in-memory store behind recorder, when there is one; the
            canary loop uses it as its stats source in demo mode.
    """

    plan: TrafficPlan
    prompts: dict[str, str]
    version_names: dict[str, str]
    client: LLMClient
    recorder: MetricsRecorder
    prometheus: PrometheusMetrics | None = None
    stats: InMemoryMetricsStore | None = None

    def set_plan(self, plan: TrafficPlan) -> None:
        """Swap the active traffic plan and publish the rollout gauge."""
        self.plan = plan
        if self.prometheus is not None:
            if plan.mode is ReleaseMode.ROLLOUT:
                permille = plan.treatment_permille
            elif plan.mode is ReleaseMode.FULL:
                permille = 1000
            else:
                permille = 0
            self.prometheus.set_treatment_permille(permille)

    def prompt_for(self, version_label: str) -> str:
        """Return the prompt text for a version label.

        Raises:
            KeyError: If the label was never configured.
        """
        return self.prompts[version_label]


@dataclass(frozen=True)
class ChatOutcome:
    """One served dialogue.

    Attributes:
        user_id: Who asked.
        group: Traffic group assigned by consistent hashing.
        version_label: "new" or "stable".
        prompt_version: Version marker of the served prompt, e.g. "v2".
        answer: The answer text.
        stars: Simulated (or measured) satisfaction 1-5.
        completed: Whether the task completed.
        response_time: Response seconds.
    """

    user_id: str
    group: str
    version_label: str
    prompt_version: str
    answer: str
    stars: int
    completed: bool
    response_time: float


def handle_chat(state: GatewayState, user_id: str, message: str) -> ChatOutcome:
    """Serve one dialogue under the current traffic plan.

    Args:
        state: Gateway state (plan, prompts, client, recorder).
        user_id: Stable user identifier for consistent hashing.
        message: Raw user message.

    Returns:
        ChatOutcome with the served version, answer and measurements.
    """
    group = state.plan.group_for(user_id)
    version_label = state.plan.version_label_for(group)
    prompt = state.prompt_for(version_label)
    response = state.client.complete(prompt, message)
    stars, _score = simulate_satisfaction(message, response.text)
    completed = is_completed(stars)
    state.recorder.record(
        version_label=version_label,
        group=group,
        stars=stars,
        completed=completed,
        response_time=response.response_time,
        ok=True,
        user_id=user_id,
        message=message,
        answer=response.text,
    )
    return ChatOutcome(
        user_id=user_id,
        group=group,
        version_label=version_label,
        prompt_version=state.version_names[version_label],
        answer=response.text,
        stars=stars,
        completed=completed,
        response_time=response.response_time,
    )


class ChatRequest(BaseModel):
    """Body of POST /chat."""

    user_id: str = Field(min_length=1, description="Stable per-user identifier")
    message: str = Field(default="", description="Raw user message")


class PlanRequest(BaseModel):
    """Body of POST /release/plan."""

    mode: Annotated[str, Field(pattern="^(off|ab|rollout|full)$")]
    treatment_permille: int = Field(default=0, ge=0, le=1000)


class ReleaseStatus(BaseModel):
    """Body of GET /release/status."""

    mode: str
    summary: str
    versions: dict[str, str]


def create_app(state: GatewayState) -> FastAPI:
    """Build the FastAPI application around a GatewayState.

    Args:
        state: Pre-configured gateway state.

    Returns:
        FastAPI app with chat, metrics, release-plan and health endpoints.
    """
    app = FastAPI(title="prompt-gray-release gateway", version="0.1.0")
    app.state.gateway = state

    @app.post("/chat")
    def chat(request: ChatRequest) -> dict[str, object]:
        outcome = handle_chat(state, request.user_id, request.message)
        return {
            "group": outcome.group,
            "version": outcome.prompt_version,
            "answer": outcome.answer,
            "stars": outcome.stars,
            "completed": outcome.completed,
            "response_time": outcome.response_time,
        }

    @app.get("/release/status")
    def release_status() -> ReleaseStatus:
        return ReleaseStatus(
            mode=state.plan.mode.value,
            summary=state.plan.summary(),
            versions=dict(state.version_names),
        )

    @app.post("/release/plan")
    def set_plan(request: PlanRequest) -> ReleaseStatus:
        state.set_plan(
            TrafficPlan(
                mode=ReleaseMode(request.mode),
                treatment_permille=request.treatment_permille,
            )
        )
        return release_status()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "OK"}

    @app.get("/metrics")
    def metrics() -> Response:
        content = b"" if state.prometheus is None else state.prometheus.expose()
        return Response(content=content, media_type="text/plain; version=0.0.4")

    return app


def build_default_state(
    prompts_dir: Path,
    client: LLMClient,
    store: InMemoryMetricsStore | None = None,
    with_prometheus: bool = True,
) -> GatewayState:
    """Assemble a GatewayState from the repo's prompts/ directory layout.

    Args:
        prompts_dir: Directory containing product_desc_v1.txt / _v2.txt.
        client: LLM backend.
        store: In-memory store used as both recorder and canary stats
            source; a fresh one is created when omitted.
        with_prometheus: Expose Prometheus metrics when True.

    Returns:
        A ready GatewayState with v1 as stable and v2 as new, plan OFF.
    """
    stable_prompt = (prompts_dir / "product_desc_v1.txt").read_text(encoding="utf-8")
    new_prompt = (prompts_dir / "product_desc_v2.txt").read_text(encoding="utf-8")
    metrics_store = store if store is not None else InMemoryMetricsStore()
    prometheus = PrometheusMetrics(CollectorRegistry()) if with_prometheus else None
    recorder: MetricsRecorder = (
        CompositeRecorder([metrics_store, prometheus]) if prometheus is not None else metrics_store
    )
    return GatewayState(
        plan=TrafficPlan(mode=ReleaseMode.OFF),
        prompts={STABLE_VERSION: stable_prompt, NEW_VERSION: new_prompt},
        version_names={
            STABLE_VERSION: prompt_version(stable_prompt),
            NEW_VERSION: prompt_version(new_prompt),
        },
        client=client,
        recorder=recorder,
        prometheus=prometheus,
        stats=metrics_store,
    )
