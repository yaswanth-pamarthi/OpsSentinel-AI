from collections import deque, defaultdict
from datetime import timedelta
import hashlib
from sqlalchemy import select
from .core import dump, uid
from .models import Event, Rule, Service, Alert, Incident, IncidentEvent, Timeline

DEFAULT_RULES = [
    ("HTTP_5XX_BURST", "http", 10, 300, "SEV-2"),
    ("DB_CONNECTION_FAILURE", "database", 5, 180, "SEV-2"),
    ("HIGH_LATENCY", "latency", 2000, 300, "SEV-3"),
    ("AUTH_FAILURE_BURST", "auth", 20, 300, "SEV-2"),
    ("RESTART_LOOP", "restart", 3, 600, "SEV-2"),
    ("ERROR_RATE_CRITICAL", "error_ratio", 0.5, 120, "SEV-1"),
]


def matches(rule, event):
    message = event.message.lower()
    attrs = event.attributes
    if getattr(rule, "pattern", "") and rule.pattern.lower() not in message:
        return False
    return {
        "http": float(attrs.get("http_status", 0)) >= 500,
        "database": ("connection timeout" in message or "connection refused" in message),
        "auth": ("failed login" in message or "authentication failed" in message),
        "restart": ("restart" in message or attrs.get("event") == "restart"),
        "latency": "latency_ms" in attrs,
        "error_ratio": "http_status" in attrs,
    }[rule.query_type]


def condition(rule, events):
    selected = [e for e in events if matches(rule, e)]
    if rule.query_type == "latency":
        values = sorted(float(e.attributes["latency_ms"]) for e in selected)
        # Require a sustained five-minute sample, not one slow request.
        sustained = (
            len(selected) >= 5
            and (selected[-1].timestamp - selected[0].timestamp).total_seconds() >= rule.window_seconds - 5
        )
        return sustained and values[
            max(0, __import__("math").ceil(0.95 * len(values)) - 1)
        ] > rule.threshold, selected
    if rule.query_type == "error_ratio":
        failures = [e for e in selected if float(e.attributes.get("http_status", 0)) >= 500]
        return len(selected) > 20 and len(failures) / len(selected) > rule.threshold, failures
    return len(selected) >= rule.threshold, selected


def freeze(db, incident, evidence):
    for event in evidence:
        snapshot = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in dump(event).items()}
        db.add(
            IncidentEvent(
                incident_id=incident.id,
                event_id=event.id,
                relationship="evidence_window",
                snapshot_json=snapshot,
            )
        )


def timeline(db, incident, type, actor, payload):
    db.add(Timeline(incident_id=incident.id, type=type, actor=actor, payload_json=payload))


def evaluate(db, service_id=None, start=None, end=None, actor="rule-engine"):
    services = db.scalars(
        select(Service).where(Service.id == service_id) if service_id else select(Service)
    ).all()
    rules = db.scalars(select(Rule).where(Rule.enabled == True)).all()
    created = []
    for service in services:
        query = (
            select(Event)
            .where(Event.service_id == service.id, Event.parse_status == "parsed")
            .order_by(Event.timestamp, Event.id)
        )
        if start:
            query = query.where(Event.timestamp >= start)
        if end:
            query = query.where(Event.timestamp <= end)
        events = db.scalars(query).all()
        for rule in rules:
            groups = defaultdict(list)
            for event in events:
                key = (
                    event.attributes.get("ip", "unknown")
                    if rule.query_type == "auth"
                    else event.host
                    if rule.query_type == "restart"
                    else "service"
                )
                groups[key].append(event)
            for group, group_events in groups.items():
                window = deque()
                episode_active = False
                for event in group_events:
                    window.append(event)
                    while window and window[0].timestamp < event.timestamp - timedelta(
                        seconds=rule.window_seconds
                    ):
                        window.popleft()
                    matched, trigger_events = condition(rule, list(window))
                    if not matched:
                        episode_active = False
                        continue
                    if episode_active:
                        continue
                    episode_active = True
                    # The first crossing event identifies the repeatable sliding-window match.
                    key = hashlib.sha256(f"{rule.id}:{service.id}:{group}:{event.id}".encode()).hexdigest()
                    if db.scalar(select(Alert).where(Alert.dedupe_key == key)):
                        continue
                    alert = Alert(
                        id=uid(),
                        rule_id=rule.id,
                        service_id=service.id,
                        window_start=event.timestamp - timedelta(seconds=rule.window_seconds),
                        window_end=event.timestamp,
                        event_count=len(trigger_events),
                        dedupe_key=key,
                    )
                    db.add(alert)
                    db.flush()
                    incident = Incident(
                        id=uid(),
                        alert_id=alert.id,
                        title=rule.name + " · " + service.name,
                        severity=rule.severity,
                        service_id=service.id,
                        detected_at=event.timestamp,
                    )
                    db.add(incident)
                    db.flush()
                    dependency_names = set(service.dependencies_json)
                    related_ids = (
                        db.scalars(select(Service.id).where(Service.name.in_(dependency_names))).all()
                        if dependency_names
                        else []
                    )
                    related = list(window)
                    if related_ids:
                        related += db.scalars(
                            select(Event).where(
                                Event.service_id.in_(related_ids),
                                Event.timestamp >= alert.window_start,
                                Event.timestamp <= alert.window_end,
                            )
                        ).all()
                    # Include available post-trigger context up to 30 seconds; freeze it once.
                    related += db.scalars(
                        select(Event).where(
                            Event.service_id == service.id,
                            Event.timestamp > event.timestamp,
                            Event.timestamp <= event.timestamp + timedelta(seconds=30),
                        )
                    ).all()
                    related = list({e.id: e for e in related}.values())
                    freeze(db, incident, related)
                    timeline(
                        db,
                        incident,
                        "DETECTED",
                        actor,
                        {
                            "rule": rule.name,
                            "window_start": alert.window_start.isoformat(),
                            "window_end": alert.window_end.isoformat(),
                            "count": len(trigger_events),
                            "evidence_count": len(related),
                        },
                    )
                    created.append(
                        {
                            "alert_id": alert.id,
                            "incident_id": incident.id,
                            "rule": rule.name,
                            "service": service.name,
                        }
                    )
    db.commit()
    return {"created": created, "count": len(created)}
