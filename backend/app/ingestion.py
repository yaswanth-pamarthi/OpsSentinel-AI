import hashlib, json, re, shlex, time, math
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from .core import uid
from .models import Service, Event


def redact(text):
    text = re.sub(r"(?i)(password|api[_-]?key|token|secret)(\s*[=:]\s*)([^\s,;]+)", r"\1\2[REDACTED]", text)
    return re.sub(r"(?i)Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", text)


def sanitize(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if re.search(r"(?i)password|token|secret|api.?key", k) else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return redact(value) if isinstance(value, str) else value


def normalize(line, default_service):
    raw = redact(line)
    status = "parsed"
    source = "json"
    data = {}
    try:
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError("Object required")
    except (ValueError, TypeError):
        if "=" in line:
            source = "key_value"
            try:
                data = dict(token.split("=", 1) for token in shlex.split(line) if "=" in token)
            except ValueError:
                data = {}
        if not data:
            source = "text"
            match = re.match(
                r"^(\S+)\s+(DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL)\s+\[?([\w.-]+)\]?\s+(.+)$", line
            )
            if match:
                data = dict(zip(["timestamp", "level", "service", "message"], match.groups()))
            else:
                data = {"message": line}
                status = "partial"
    data = sanitize(data)
    if source == "json":
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    stamp = str(data.get("timestamp", data.get("time", "")))
    try:
        timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        timestamp = (
            timestamp.replace(tzinfo=timezone.utc)
            if timestamp.tzinfo is None
            else timestamp.astimezone(timezone.utc)
        )
    except ValueError:
        timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc)
        status = "partial"
    attrs = dict(data.get("attributes") or {}) if isinstance(data.get("attributes"), dict) else {}
    for name in ("http_status", "latency_ms", "ip", "event", "database"):
        if name in data:
            attrs[name] = data[name]
    for name in ("http_status", "latency_ms"):
        if name in attrs:
            try:
                attrs[name] = float(attrs[name])
                if not math.isfinite(attrs[name]):
                    raise ValueError("Non-finite metric")
            except (ValueError, TypeError):
                attrs.pop(name)
                status = "partial"
    result = {
        "timestamp": timestamp,
        "service": str(data.get("service", default_service)),
        "level": str(data.get("level", "UNKNOWN")).upper(),
        "message": str(data.get("message", line)),
        "trace_id": str(data["trace_id"]) if data.get("trace_id") is not None else None,
        "host": str(data.get("host", "demo-host")),
        "source_type": source,
        "attributes": attrs,
        "raw_line": raw,
        "original_timestamp": stamp,
        "parse_status": status,
    }
    # Semantic identity, independent of equivalent JSON whitespace/key order.
    result["hash"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("raw_line", "source_type", "original_timestamp")},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return result


def ingest(db, lines, default_service):
    start = time.perf_counter()
    catalog = {s.name: s.id for s in db.scalars(select(Service))}
    if default_service not in catalog:
        raise HTTPException(422, "Default service is not in the service catalog")
    rows = []
    partial = 0
    unknown = []
    for line in lines:
        if not line.strip():
            continue
        event = normalize(line, default_service)
        if event["service"] not in catalog:
            unknown.append(event["service"])
            event["attributes"]["unregistered_service"] = event["service"]
            event["service"] = default_service
            event["parse_status"] = "partial"
        partial += event["parse_status"] == "partial"
        service = event.pop("service")
        rows.append({"id": uid(), "service_id": catalog[service], **event})
    inserted = 0
    for i in range(0, len(rows), 500):
        query = (
            insert(Event)
            .values(rows[i : i + 500])
            .on_conflict_do_nothing(index_elements=["hash"])
            .returning(Event.id)
        )
        inserted += len(db.scalars(query).all())
    db.commit()
    return {
        "input_lines": len(rows),
        "inserted": inserted,
        "duplicates": len(rows) - inserted,
        "partial": partial,
        "retained": len(rows),
        "unregistered_services": sorted(set(unknown)),
        "duration_seconds": round(time.perf_counter() - start, 3),
    }


def signature(message):
    return re.sub(r"\b[\da-f-]{6,}\b|\b\d+\b", "<value>", message.lower())
