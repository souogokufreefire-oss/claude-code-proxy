"""Unit tests for the per-provider metrics registry and SSE output token tracker."""

from core.metrics import MetricsRegistry, OutputTokenTracker, ProviderMetrics


def _message_delta_frame(output_tokens: int) -> str:
    return (
        "event: message_delta\n"
        f'data: {{"type": "message_delta", "usage": {{"input_tokens": 10, "output_tokens": {output_tokens}}}}}\n\n'
    )


def test_registry_records_request_with_tokens():
    registry = MetricsRegistry()

    registry.record_request("open_router", 120)

    entry = registry.snapshot()["open_router"]
    assert entry.requests == 1
    assert entry.tokens_in == 120


def test_registry_accumulates_counts_per_provider():
    registry = MetricsRegistry()

    registry.record_request("groq", 10)
    registry.record_request("groq", 20)
    registry.record_stream_result("groq", output_tokens=15)
    registry.record_failover("groq")

    entry = registry.snapshot()["groq"]
    assert entry.requests == 2
    assert entry.tokens_in == 30
    assert entry.tokens_out == 15
    assert entry.failovers == 1
    assert entry.errors == 0


def test_registry_records_error():
    registry = MetricsRegistry()

    registry.record_request("open_router", 5)
    registry.record_stream_result("open_router", error=True)

    entry = registry.snapshot()["open_router"]
    assert entry.errors == 1
    assert entry.tokens_out == 0


def test_registry_normalizes_provider_ids_to_lowercase():
    registry = MetricsRegistry()

    registry.record_request("OPEN_ROUTER", 1)
    registry.record_request("open_router", 2)

    snapshot = registry.snapshot()
    assert list(snapshot) == ["open_router"]
    assert snapshot["open_router"].requests == 2


def test_registry_ignores_negative_tokens():
    registry = MetricsRegistry()

    registry.record_request("groq", -5)
    registry.record_stream_result("groq", output_tokens=-1)

    entry = registry.snapshot()["groq"]
    assert entry.tokens_in == 0
    assert entry.tokens_out == 0


def test_registry_snapshot_is_isolated_copy():
    registry = MetricsRegistry()
    registry.record_request("groq", 10)

    snapshot = registry.snapshot()
    snapshot["groq"].requests = 999

    assert registry.snapshot()["groq"].requests == 1


def test_summary_line_reports_no_requests_when_empty():
    assert MetricsRegistry().summary_log_line() == "no requests recorded"


def test_summary_line_lists_providers_sorted():
    registry = MetricsRegistry()
    registry.record_request("groq", 10)
    registry.record_request("open_router", 20)

    line = registry.summary_log_line()

    assert "groq: requests=1 errors=0 failovers=0 tokens_in=10 tokens_out=0" in line
    assert "open_router: requests=1" in line
    assert line.index("groq") < line.index("open_router")


def test_provider_metrics_defaults_to_zero():
    entry = ProviderMetrics()
    assert entry.requests == 0
    assert entry.errors == 0
    assert entry.failovers == 0
    assert entry.tokens_in == 0
    assert entry.tokens_out == 0


def test_tracker_extracts_output_tokens_from_message_delta():
    tracker = OutputTokenTracker()

    tracker.feed(_message_delta_frame(42))

    assert tracker.output_tokens == 42


def test_tracker_keeps_last_message_delta_usage():
    tracker = OutputTokenTracker()

    tracker.feed(_message_delta_frame(10))
    tracker.feed(_message_delta_frame(25))

    assert tracker.output_tokens == 25


def test_tracker_handles_chunks_split_across_frames():
    tracker = OutputTokenTracker()
    frame = _message_delta_frame(7)

    tracker.feed(frame[:10])
    tracker.feed(frame[10:])

    assert tracker.output_tokens == 7


def test_tracker_ignores_non_message_delta_frames():
    tracker = OutputTokenTracker()

    tracker.feed('event: content_block_delta\ndata: {"type": "x"}\n\n')

    assert tracker.output_tokens == 0


def test_tracker_ignores_malformed_json():
    tracker = OutputTokenTracker()

    tracker.feed("event: message_delta\ndata: {not-json}\n\n")

    assert tracker.output_tokens == 0


def test_tracker_ignores_non_integer_output_tokens():
    tracker = OutputTokenTracker()
    frame = (
        "event: message_delta\n"
        'data: {"type": "message_delta", "usage": {"output_tokens": "many"}}\n\n'
    )

    tracker.feed(frame)

    assert tracker.output_tokens == 0


def test_tracker_defaults_to_zero():
    assert OutputTokenTracker().output_tokens == 0
