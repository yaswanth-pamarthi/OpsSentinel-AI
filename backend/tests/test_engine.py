from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from app.ingestion import normalize, redact
from app.detection import condition
from app.rca import analyze, proposal_from_knowledge


@pytest.mark.parametrize(
    "line,format",
    [
        (
            '{"timestamp":"2026-10-14T10:00:00Z","level":"ERROR","service":"checkout-api","message":"database connection timeout"}',
            "json",
        ),
        (
            'timestamp=2026-10-14T10:00:00Z level=ERROR service=checkout-api message="database connection timeout"',
            "key_value",
        ),
        ("2026-10-14T10:00:00Z ERROR checkout-api database connection timeout", "text"),
    ],
)
def test_three_formats(line, format):
    e = normalize(line, "checkout-api")
    assert e["parse_status"] == "parsed" and e["source_type"] == format and e["timestamp"].tzinfo


def test_malformed_line_retained():
    e = normalize("unexpected garbage", "checkout-api")
    assert e["parse_status"] == "partial" and e["raw_line"] == "unexpected garbage"


def test_timezone_normalization():
    a = normalize('{"timestamp":"2026-10-14T15:30:00+05:30","message":"test"}', "checkout-api")
    assert a["timestamp"].hour == 10


def test_semantic_event_hash():
    a = normalize('{"timestamp":"2026-10-14T10:00:00Z", "message":"test"}', "checkout-api")
    b = normalize('{"message":"test","timestamp":"2026-10-14T10:00:00Z"}', "checkout-api")
    assert a["hash"] == b["hash"]


def test_secrets_redacted():
    assert "abc123" not in redact("password=abc123 token:abc123 Bearer abc123")
    e = normalize(
        '{"timestamp":"2026-10-14T10:00:00Z","message":"password=abc123","attributes":{"api_key":"hidden"}}',
        "checkout-api",
    )
    assert e["attributes"]["api_key"] == "[REDACTED]" and "abc123" not in e["message"]
    assert "hidden" not in e["raw_line"] and "abc123" not in e["raw_line"]


def event(index, status=500, latency=100):
    return SimpleNamespace(
        id=str(index),
        timestamp=datetime(2026, 10, 14, 10, tzinfo=timezone.utc) + timedelta(seconds=index * 5),
        message="HTTP request",
        attributes={"http_status": status, "latency_ms": latency},
        host="host",
    )


def test_single_500_does_not_burst():
    rule = SimpleNamespace(query_type="http", threshold=10, window_seconds=300)
    assert not condition(rule, [event(0)])[0]
    assert condition(rule, [event(i) for i in range(10)])[0]


def test_critical_ratio_requires_volume():
    rule = SimpleNamespace(query_type="error_ratio", threshold=0.5, window_seconds=120)
    assert not condition(rule, [event(i) for i in range(20)])[0]
    assert condition(rule, [event(i) for i in range(21)])[0]


def test_latency_requires_sustained_window():
    rule = SimpleNamespace(query_type="latency", threshold=2000, window_seconds=300)
    assert not condition(rule, [event(0, 200, 3100)])[0]
    assert condition(rule, [event(i, 200, 3100) for i in range(61)])[0]


def test_rca_valid_references_and_alternatives():
    events = [
        {
            "id": str(i),
            "timestamp": f"2026-10-14T10:00:{i:02d}Z",
            "level": "ERROR",
            "message": "database connection timeout",
            "attributes": {"http_status": 500, "latency_ms": 5000},
            "trace_id": "test",
        }
        for i in range(10)
    ]
    payload = analyze(events, SimpleNamespace(dependencies_json=["orders-db"]), [])
    assert payload["hypotheses"][0]["cause"] == "Database connection pool exhaustion"
    assert payload["hypotheses"][0]["score"] > payload["hypotheses"][1]["score"]
    ids = {e["id"] for e in events}
    assert all(set(f["event_ids"]) <= ids for f in payload["confirmed_facts"])
    assert payload["hypotheses"][0]["score_breakdown"]["confirmed_by_resolution"] == 0


def test_commands_only_text_and_risk_flag():
    p = proposal_from_knowledge(
        [{"section": "# Diagnosis", "text": "DROP DATABASE example;", "chunk_id": "x"}]
    )
    assert p["executed"] is False and p["requires_approval"] and p["diagnostics"][0]["risk"] == "high"


def test_rule_literal_pattern_filters_matching_events():
    rule = SimpleNamespace(query_type="http", pattern="database timeout", threshold=1, window_seconds=300)
    assert not condition(rule, [event(0)])[0]
    e = event(0)
    e.message = "Database timeout caused HTTP failure"
    assert condition(rule, [e])[0]


@pytest.mark.parametrize(
    "level,message,attributes",
    [
        ("INFO", "payment upstream response slow", {"latency_ms": 3100, "http_status": 200}),
        ("WARN", "service restart after deployment", {"http_status": 200}),
    ],
)
def test_non_error_operational_failures_have_confirmed_facts(level, message, attributes):
    events = [
        {
            "id": "failure-event",
            "timestamp": "2026-10-14T10:00:00Z",
            "level": level,
            "message": message,
            "attributes": attributes,
            "trace_id": None,
        }
    ]
    result = analyze(events, SimpleNamespace(dependencies_json=[]), [])
    assert result["confirmed_facts"][0]["event_ids"] == ["failure-event"]
    assert result["hypotheses"][0]["score_breakdown"]["first_failure"] == 30
