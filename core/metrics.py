"""Per-provider runtime metrics with JSON log summaries.

Counters are aggregate and never contain payload data, prompts, or keys.
The periodic summary is emitted as a single JSON log line for observability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from threading import RLock

from loguru import logger


@dataclass(slots=True)
class ProviderMetrics:
    """Cumulative counters for one provider."""

    requests: int = 0
    errors: int = 0
    failovers: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class MetricsRegistry:
    """Thread-safe per-provider counters."""

    def __init__(self) -> None:
        self._counters: dict[str, ProviderMetrics] = {}
        self._lock = RLock()

    def _entry(self, provider_id: str) -> ProviderMetrics:
        normalized = provider_id.lower()
        with self._lock:
            entry = self._counters.get(normalized)
            if entry is None:
                entry = ProviderMetrics()
                self._counters[normalized] = entry
            return entry

    def record_request(self, provider_id: str, tokens_in: int) -> None:
        entry = self._entry(provider_id)
        with self._lock:
            entry.requests += 1
            entry.tokens_in += max(tokens_in, 0)

    def record_stream_result(
        self,
        provider_id: str,
        *,
        output_tokens: int = 0,
        error: bool = False,
    ) -> None:
        entry = self._entry(provider_id)
        with self._lock:
            if error:
                entry.errors += 1
            entry.tokens_out += max(output_tokens, 0)

    def record_failover(self, provider_id: str) -> None:
        entry = self._entry(provider_id)
        with self._lock:
            entry.failovers += 1

    def snapshot(self) -> dict[str, ProviderMetrics]:
        with self._lock:
            return {
                provider_id: ProviderMetrics(
                    entry.requests,
                    entry.errors,
                    entry.failovers,
                    entry.tokens_in,
                    entry.tokens_out,
                )
                for provider_id, entry in sorted(self._counters.items())
            }

    def summary_log_line(self) -> str:
        snapshot = self.snapshot()
        if not snapshot:
            return "no requests recorded"
        return ", ".join(
            f"{provider_id}: requests={m.requests} errors={m.errors} "
            f"failovers={m.failovers} tokens_in={m.tokens_in} tokens_out={m.tokens_out}"
            for provider_id, m in snapshot.items()
        )

    def log_summary(self) -> None:
        logger.info("PROVIDER_METRICS: {}", self.summary_log_line())


class OutputTokenTracker:
    """Extract the final ``usage.output_tokens`` from streamed SSE frames."""

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._buf: str | None = None
        self._output_tokens = 0

    def feed(self, chunk: str) -> None:
        self._chunks.append(chunk)
        self._buf = None
        while True:
            buf = self._current_buffer()
            sep = buf.find("\n\n")
            if sep < 0:
                break
            frame = buf[:sep]
            self._set_buffer(buf[sep + 2 :])
            self._observe_frame(frame)

    def _current_buffer(self) -> str:
        if self._buf is None:
            self._buf = "".join(self._chunks)
        return self._buf

    def _set_buffer(self, value: str) -> None:
        self._buf = value
        self._chunks = [value]

    def _observe_frame(self, frame: str) -> None:
        event_name = ""
        data_parts: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_parts.append(line[len("data:") :].strip())
        if event_name != "message_delta":
            return
        for raw in data_parts:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            usage = data.get("usage")
            if isinstance(usage, dict):
                tokens = usage.get("output_tokens")
                if isinstance(tokens, int):
                    self._output_tokens = tokens

    @property
    def output_tokens(self) -> int:
        return self._output_tokens


metrics_registry = MetricsRegistry()
