"""Metrics recording and windowed snapshots.

Two backends share one purpose:

* InMemoryMetricsStore -- demo, tests and the canary loop's stats source.
  Keeps a bounded deque of timestamped records plus the worst dialogue
  samples for post-mortems. Time is injected via a clock callable so the
  demo can compress hours into seconds.
* PrometheusMetrics -- production recording for /metrics scraping (Grafana
  panels and Alertmanager rules). PrometheusQueryClient reads snapshots
  back from the Prometheus HTTP API for the circuit breaker.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

MAX_RETAINED_RECORDS = 50_000
MAX_RETAINED_SAMPLES = 200


@dataclass(frozen=True)
class WindowStats:
    """Aggregated metrics for one prompt version over a time window.

    Attributes:
        requests: Dialogues recorded in the window.
        satisfaction: Average stars (1-5).
        completion_rate: Share of dialogues with the task completed.
        response_time: Average response seconds.
        error_rate: Share of calls that errored.
    """

    requests: int
    satisfaction: float
    completion_rate: float
    response_time: float
    error_rate: float

    @classmethod
    def empty(cls) -> WindowStats:
        """Zero-value stats used when a version saw no traffic."""
        return cls(requests=0, satisfaction=0.0, completion_rate=0.0, response_time=0.0, error_rate=0.0)


@dataclass(frozen=True)
class DialogueSample:
    """A single dialogue kept for post-mortem analysis (pit #4)."""

    user_id: str
    message: str
    answer: str
    stars: int
    version_label: str


class MetricsRecorder(Protocol):
    """Sink for per-dialogue measurements."""

    def record(
        self,
        *,
        version_label: str,
        group: str,
        stars: int,
        completed: bool,
        response_time: float,
        ok: bool = True,
        user_id: str = "",
        message: str = "",
        answer: str = "",
    ) -> None:
        """Record one completed dialogue."""
        ...


class StatsSource(Protocol):
    """Provider of windowed stats, e.g. for the circuit breaker."""

    def snapshot(self, version_label: str, window_seconds: int) -> WindowStats:
        """Aggregate stats for one version over the trailing window."""
        ...


@dataclass(frozen=True)
class _Record:
    timestamp: float
    version_label: str
    group: str
    stars: int
    completed: bool
    response_time: float
    ok: bool


class CompositeRecorder:
    """Fan out one dialogue measurement to several sinks.

    The gateway uses this to feed both the in-memory store (canary stats
    source, worst-sample retention) and the Prometheus registry (Grafana /
    Alertmanager) from a single record() call.
    """

    def __init__(self, recorders: list[MetricsRecorder]) -> None:
        """Create a composite sink.

        Args:
            recorders: Sinks to fan out to, in order.
        """
        self._recorders = recorders

    def record(
        self,
        *,
        version_label: str,
        group: str,
        stars: int,
        completed: bool,
        response_time: float,
        ok: bool = True,
        user_id: str = "",
        message: str = "",
        answer: str = "",
    ) -> None:
        """Forward one dialogue measurement to every sink."""
        for recorder in self._recorders:
            recorder.record(
                version_label=version_label,
                group=group,
                stars=stars,
                completed=completed,
                response_time=response_time,
                ok=ok,
                user_id=user_id,
                message=message,
                answer=answer,
            )


class InMemoryMetricsStore:
    """In-memory recorder + stats source with injectable clock.

    Attributes:
        clock: Returns the current epoch seconds; inject a fake in tests
            and in the demo to compress observation windows.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        """Create a store.

        Args:
            clock: Time source; defaults to time.time.
        """
        self.clock = clock
        self._records: deque[_Record] = deque(maxlen=MAX_RETAINED_RECORDS)
        self._worst_samples: deque[DialogueSample] = deque(maxlen=MAX_RETAINED_SAMPLES)

    def record(
        self,
        *,
        version_label: str,
        group: str,
        stars: int,
        completed: bool,
        response_time: float,
        ok: bool = True,
        user_id: str = "",
        message: str = "",
        answer: str = "",
    ) -> None:
        """Store one dialogue measurement, keeping low-star samples.

        Args:
            version_label: "new" or "stable".
            group: Traffic group ("A" / "B" / "treatment" / "control").
            stars: Satisfaction stars 1-5.
            completed: Whether the user's task completed.
            response_time: Response seconds.
            ok: False when the call errored (answer unusable).
            user_id: Optional, for worst-sample retention.
            message: Optional user message, for worst-sample retention.
            answer: Optional answer text, for worst-sample retention.
        """
        now = self.clock()
        self._records.append(
            _Record(
                timestamp=now,
                version_label=version_label,
                group=group,
                stars=stars,
                completed=completed,
                response_time=response_time,
                ok=ok,
            )
        )
        if stars <= 2 and message:
            self._worst_samples.append(
                DialogueSample(
                    user_id=user_id,
                    message=message,
                    answer=answer,
                    stars=stars,
                    version_label=version_label,
                )
            )

    def snapshot(self, version_label: str, window_seconds: int) -> WindowStats:
        """Aggregate one version's records inside the trailing window.

        Args:
            version_label: "new" or "stable".
            window_seconds: Trailing window length in seconds.

        Returns:
            WindowStats, or empty stats when no traffic qualified.
        """
        cutoff = self.clock() - window_seconds
        in_window = [
            record for record in self._records if record.version_label == version_label and record.timestamp >= cutoff
        ]
        if not in_window:
            return WindowStats.empty()
        count = len(in_window)
        return WindowStats(
            requests=count,
            satisfaction=round(sum(record.stars for record in in_window) / count, 4),
            completion_rate=round(sum(1 for record in in_window if record.completed) / count, 4),
            response_time=round(sum(record.response_time for record in in_window) / count, 3),
            error_rate=round(sum(1 for record in in_window if not record.ok) / count, 4),
        )

    def worst_samples(self, limit: int = 10, version_label: str | None = None) -> list[DialogueSample]:
        """Return the most recent low-star dialogues, newest first.

        Args:
            limit: Maximum number of samples to return.
            version_label: When given, restrict to that version ("new" /
                "stable"); a post-mortem for a rolled-back release only
                wants evidence from the candidate prompt.
        """
        samples = [
            sample for sample in self._worst_samples if version_label is None or sample.version_label == version_label
        ]
        return samples[-limit:][::-1]


class PrometheusMetrics:
    """Production recorder exposing bot_* metrics on /metrics."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Create (or attach to) a Prometheus registry.

        Args:
            registry: Explicit registry; a fresh one is created when omitted
                so tests never pollute the default registry.
        """
        self.registry = registry if registry is not None else CollectorRegistry()
        self.requests = Counter("bot_requests_total", "Dialogues handled", ["version", "group"], registry=self.registry)
        self.errors = Counter("bot_errors_total", "Failed dialogues", ["version"], registry=self.registry)
        self.task_completed = Counter(
            "bot_task_completed_total", "Task-completed dialogues", ["version"], registry=self.registry
        )
        self.response_seconds = Histogram(
            "bot_response_seconds",
            "Response time in seconds",
            ["version"],
            buckets=(0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 5.0),
            registry=self.registry,
        )
        self.satisfaction = Histogram(
            "bot_satisfaction",
            "End-of-dialogue star rating 1-5",
            ["version"],
            buckets=(1, 2, 3, 4, 5),
            registry=self.registry,
        )
        self.treatment_permille = Gauge(
            "bot_treatment_permille",
            "Current rollout percentage of the new prompt, in per-mille",
            registry=self.registry,
        )

    def record(
        self,
        *,
        version_label: str,
        group: str,
        stars: int,
        completed: bool,
        response_time: float,
        ok: bool = True,
        user_id: str = "",  # noqa: ARG003 -- kept for recorder-interface parity
        message: str = "",  # noqa: ARG003 -- kept for recorder-interface parity
        answer: str = "",  # noqa: ARG003 -- kept for recorder-interface parity
    ) -> None:
        """Emit Prometheus series for one dialogue.

        Args:
            version_label: "new" or "stable".
            group: Traffic group.
            stars: Satisfaction stars 1-5.
            completed: Whether the task completed.
            response_time: Response seconds.
            ok: False when the call errored.
            user_id: Unused here (interface parity with InMemoryMetricsStore).
            message: Unused here (interface parity).
            answer: Unused here (interface parity).
        """
        self.requests.labels(version=version_label, group=group).inc()
        self.satisfaction.labels(version=version_label).observe(stars)
        self.response_seconds.labels(version=version_label).observe(response_time)
        if completed:
            self.task_completed.labels(version=version_label).inc()
        if not ok:
            self.errors.labels(version=version_label).inc()

    def set_treatment_permille(self, permille: int) -> None:
        """Publish the current rollout percentage to the gauge."""
        self.treatment_permille.set(permille)

    def expose(self) -> bytes:
        """Render the registry in Prometheus text exposition format."""
        return generate_latest(self.registry)


class PrometheusQueryClient:
    """StatsSource backed by the Prometheus HTTP API (production breaker)."""

    def __init__(self, base_url: str = "http://localhost:9090") -> None:
        """Create a query client.

        Args:
            base_url: Prometheus base URL.
        """
        self.base_url = base_url.rstrip("/")

    def _scalar(self, query: str) -> float:
        response = httpx.get(f"{self.base_url}/api/v1/query", params={"query": query}, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        results = payload.get("data", {}).get("result", [])
        if not results:
            return 0.0
        return float(results[0]["value"][1])

    def snapshot(self, version_label: str, window_seconds: int) -> WindowStats:  # noqa: ARG002
        """Aggregate cumulative counters into WindowStats.

        Counter-based (since start); to evaluate over a pure sliding window,
        swap these queries for rate()/increase() expressions at the call
        site. The demo and tests always use InMemoryMetricsStore.

        Args:
            version_label: "new" or "stable".
            window_seconds: Unused for cumulative queries; kept for
                StatsSource interface parity.

        Returns:
            Aggregated WindowStats from Prometheus.
        """
        requests = self._scalar(f'sum(bot_requests_total{{version="{version_label}"}})')
        if requests <= 0:
            return WindowStats.empty()
        satisfaction = self._scalar(
            f'sum(bot_satisfaction_sum{{version="{version_label}"}}) '
            f'/ sum(bot_satisfaction_count{{version="{version_label}"}})'
        )
        completion = self._scalar(f'sum(bot_task_completed_total{{version="{version_label}"}}) / {requests}')
        response_time = self._scalar(
            f'sum(bot_response_seconds_sum{{version="{version_label}"}}) '
            f'/ sum(bot_response_seconds_count{{version="{version_label}"}})'
        )
        error_rate = self._scalar(f'sum(bot_errors_total{{version="{version_label}"}}) / {requests}')
        return WindowStats(
            requests=int(requests),
            satisfaction=round(satisfaction, 4),
            completion_rate=round(completion, 4),
            response_time=round(response_time, 3),
            error_rate=round(error_rate, 4),
        )

    def __call__(self, version_label: str, window_seconds: int) -> WindowStats:
        """Allow the client to be passed directly as a stats source."""
        return self.snapshot(version_label, window_seconds)
