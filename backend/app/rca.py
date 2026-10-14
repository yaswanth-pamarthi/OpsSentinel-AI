from collections import defaultdict
from .ingestion import signature


def analyze(events, service, knowledge):
    ordered = sorted(events, key=lambda e: (e["timestamp"], e["id"]))
    failure_patterns = (
        "connection timeout",
        "connection refused",
        "failed login",
        "authentication failed",
        "restart",
    )
    errors = [
        e
        for e in ordered
        if e["level"] in ("ERROR", "CRITICAL")
        or float(e["attributes"].get("http_status", 0)) >= 500
        or float(e["attributes"].get("latency_ms", 0)) > 2000
        or any(pattern in e["message"].lower() for pattern in failure_patterns)
    ]
    groups = defaultdict(list)
    for e in errors:
        groups[signature(e["message"])].append(e["id"])
    facts = [{"statement": f"{e['timestamp']}: {e['message']}", "event_ids": [e["id"]]} for e in errors[:8]]
    db = [
        e
        for e in errors
        if "connection timeout" in e["message"].lower() or "connection refused" in e["message"].lower()
    ]
    auth = [
        e
        for e in errors
        if "failed login" in e["message"].lower() or "authentication failed" in e["message"].lower()
    ]
    restart = [e for e in ordered if "restart" in e["message"].lower()]
    slow = [e for e in ordered if float(e["attributes"].get("latency_ms", 0)) > 2000]
    templates = [
        (
            "Database connection pool exhaustion",
            db,
            ["database active connection count", "pool configured limit"],
        ),
        (
            "Repeated unauthorized authentication attempts",
            auth,
            ["identity-provider audit trail", "source-IP ownership"],
        ),
        ("Deployment or configuration instability", restart, ["deployment manifest and change diff"]),
        ("Upstream dependency latency or saturation", slow, ["upstream utilization and distributed traces"]),
    ]
    hypotheses = []
    earliest = errors[0]["id"] if errors else ordered[0]["id"] if ordered else None
    for cause, support, missing in templates:
        if not support:
            continue
        evidence = [e["id"] for e in support]
        first = earliest in evidence
        majority = len(support) >= max(1, len(errors) / 2)
        # Similar resolved incidents count only when retrieval actually returns one.
        similar = any(
            k["source_type"] == "incident_report"
            and any(w in k["text"].lower() for w in cause.lower().split()[:2])
            for k in knowledge
        )
        dependency = bool(service.dependencies_json) and bool(db) and cause.startswith("Database")
        contradictory = (
            [e["id"] for e in ordered if "database healthy" in e["message"].lower()]
            if cause.startswith("Database")
            else []
        )
        score = (
            (30 if first else 0)
            + (25 if majority else 0)
            + (20 if similar else 0)
            + (15 if dependency else 0)
            - 25 * len(contradictory)
        )
        hypotheses.append(
            {
                "cause": cause,
                "supporting_event_ids": evidence[:60],
                "contradicting_event_ids": contradictory,
                "explains": ["first failure"] if first else ["related error group"],
                "score": score,
                "score_breakdown": {
                    "first_failure": 30 if first else 0,
                    "majority": 25 if majority else 0,
                    "similar_resolved_incident": 20 if similar else 0,
                    "dependency": 15 if dependency else 0,
                    "confirmed_by_resolution": 0,
                    "contradictions": -25 * len(contradictory),
                },
                "confidence": "high" if score >= 65 else "medium" if score >= 40 else "low",
                "missing_evidence": missing,
            }
        )
    hypotheses.sort(key=lambda h: -h["score"])
    if not hypotheses:
        hypotheses = [
            {
                "cause": "Insufficient evidence to distinguish service failure causes",
                "supporting_event_ids": [e["id"] for e in errors[:10]],
                "contradicting_event_ids": [],
                "explains": [],
                "score": 0,
                "score_breakdown": {},
                "confidence": "low",
                "missing_evidence": ["metrics and traces"],
            }
        ]
    for i, h in enumerate(hypotheses):
        h["rank"] = i + 1
    return {
        "confirmed_facts": facts,
        "hypotheses": hypotheses,
        "alternatives": hypotheses[1:],
        "missing_evidence": list({m for h in hypotheses for m in h["missing_evidence"]}),
        "recommended_checks": ["Inspect cited runbook diagnostics and collect missing metrics."],
        "error_groups": dict(groups),
        "event_order": [e["id"] for e in ordered],
        "correlation": {
            "shared_traces": {
                trace: [e["id"] for e in ordered if e.get("trace_id") == trace]
                for trace in sorted({e["trace_id"] for e in ordered if e.get("trace_id")})[:20]
            }
        },
        "confidence_note": "Evidence score is a heuristic ranking, not a calibrated probability.",
    }


def proposal_from_knowledge(knowledge):
    diagnostics = []
    fix = []
    rollback = []
    validation = []
    containment = []
    for chunk in knowledge:
        section = chunk["section"].lower()
        text = chunk["text"]
        entry = {"step": text, "source_chunk_id": chunk["chunk_id"], "risk": "medium"}
        if "diagnos" in section:
            entry["risk"] = "read-only"
            diagnostics.append(entry)
        elif "rollback" in section:
            rollback.append(entry)
        elif "validat" in section:
            validation.append(entry)
        elif "contain" in section or "mitigat" in section:
            containment.append(entry)
        elif "fix" in section or "remediat" in section:
            fix.append(entry)
    risk_terms = ["drop ", "delete ", "rm -rf", "shutdown", "truncate "]
    for entry in diagnostics + fix + rollback + validation + containment:
        if any(term in entry["step"].lower() for term in risk_terms):
            entry["risk"] = "high"
    return {
        "immediate_containment": containment,
        "diagnostics": diagnostics,
        "permanent_fix": fix,
        "rollback": rollback,
        "validation": validation,
        "requires_approval": True,
        "executed": False,
        "limitations": [
            "No live infrastructure connection. All actions are text proposals.",
            "Missing procedure sections require engineer-authored revision.",
        ]
        if not all([diagnostics, fix, rollback, validation])
        else ["Local simulator: engineer records actual action and validation separately."],
    }
