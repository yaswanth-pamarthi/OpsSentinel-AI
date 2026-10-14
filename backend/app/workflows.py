import sqlite3, threading
from typing import TypedDict
from sqlalchemy import select
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from .core import ROOT, Session, now, uid
from .models import Incident, IncidentEvent, Service, Run, Output, Hypothesis, Proposal
from .detection import timeline
from .knowledge import retrieve
from .ai import commentary
from .rca import analyze, proposal_from_knowledge


class State(TypedDict, total=False):
    incident_id: str
    run_id: str
    monitoring: dict
    logs: dict
    security: dict
    rca: dict
    runbook: dict
    notification: dict
    proposal_id: str
    decision: dict
    resolution: dict
    report: dict


def context(state):
    with Session() as db:
        incident = db.get(Incident, state["incident_id"])
        service = db.get(Service, incident.service_id)
        events = [
            e.snapshot_json
            for e in db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == incident.id))
        ]
        return incident, service, events


def record(state, name, payload, ids, started):
    summary, model = commentary(name, payload, ids)
    with Session() as db:
        db.add(
            Output(
                run_id=state["run_id"],
                agent_name=name,
                payload_json={**payload, "ai_commentary": summary},
                inputs_json={"evidence_ids": ids, "incident_id": state["incident_id"]},
                model_json=model,
                started_at=started,
                completed_at=now(),
            )
        )
        timeline(
            db,
            db.get(Incident, state["incident_id"]),
            "AGENT_COMPLETED",
            "agent:" + name,
            {"run_id": state["run_id"], "agent": name, "prompt_version": "grounded-v1"},
        )
        db.commit()
    return {**payload, "ai_commentary": summary}


def monitoring(state):
    start = now()
    incident, service, events = context(state)
    payload = {
        "service": service.name,
        "severity": incident.severity,
        "detection": incident.title,
        "evidence_count": len(events),
        "first_event": min((e["timestamp"] for e in events), default=None),
    }
    return {"monitoring": record(state, "Monitoring", payload, [e["id"] for e in events[:5]], start)}


def logs(state):
    start = now()
    incident, service, events = context(state)
    analysis = analyze(events, service, [])
    payload = {k: analysis[k] for k in ["error_groups", "event_order", "correlation"]}
    return {"logs": record(state, "Log Analysis", payload, [e["id"] for e in events], start)}


def security(state):
    start = now()
    _, _, events = context(state)
    auth = [
        e
        for e in events
        if "failed login" in e["message"].lower() or "authentication failed" in e["message"].lower()
    ]
    payload = {
        "authentication_failures": len(auth),
        "applicable": bool(auth),
        "escalation_flag": len(auth) >= 20,
        "source_ips": sorted({str(e["attributes"].get("ip", "unknown")) for e in auth}),
        "assessment": "Repeated authentication failures require investigation; attribution is unconfirmed."
        if auth
        else "No authentication failure indicators in this evidence window.",
        "limitations": ["No identity-provider integration or threat-intelligence feed."],
    }
    return {"security": record(state, "Security", payload, [e["id"] for e in auth], start)}


def rca(state):
    start = now()
    incident, service, events = context(state)
    with Session() as db:
        knowledge = retrieve(db, service, incident.title + " " + " ".join(e["message"] for e in events[:10]))
    payload = analyze(events, service, knowledge)
    with Session() as db:
        for hypothesis in payload["hypotheses"]:
            db.add(
                Hypothesis(
                    incident_id=incident.id,
                    run_id=state["run_id"],
                    rank=hypothesis["rank"],
                    cause=hypothesis["cause"],
                    evidence_json=hypothesis,
                    score=hypothesis["score"],
                    confidence=hypothesis["confidence"],
                )
            )
        obj = db.get(Incident, incident.id)
        obj.status = "ROOT_CAUSE_IDENTIFIED"
        timeline(
            db,
            obj,
            "ROOT_CAUSE_IDENTIFIED",
            "workflow",
            {"note": "Ranked hypotheses; causality remains unconfirmed."},
        )
        db.commit()
    return {"rca": record(state, "Root Cause", payload, [e["id"] for e in events], start)}


def runbook(state):
    start = now()
    incident, service, events = context(state)
    with Session() as db:
        query = " ".join(
            [incident.title, state["rca"]["hypotheses"][0]["cause"]] + list(state["rca"]["error_groups"])[:3]
        )
        evidence = retrieve(db, service, query, complete_runbook=True)
        proposal = proposal_from_knowledge(evidence)
        proposal["warnings"] = sorted({c["warning"] for c in evidence if c.get("warning")})
        obj = Proposal(id=uid(), incident_id=incident.id, run_id=state["run_id"], payload_json=proposal)
        db.add(obj)
        incident = db.get(Incident, incident.id)
        incident.status = "REMEDIATION_PROPOSED"
        timeline(db, incident, "REMEDIATION_PROPOSED", "workflow", {"proposal_id": obj.id, "executed": False})
        db.commit()
        proposal_id = obj.id
    return {
        "runbook": record(
            state,
            "Runbook",
            {"retrieved": evidence, "proposal": proposal},
            [c["chunk_id"] for c in evidence],
            start,
        ),
        "proposal_id": proposal_id,
    }


def notification(state):
    start = now()
    incident, service, _ = context(state)
    payload = {
        "preview": {
            "channel": "local-preview",
            "subject": f"[{incident.severity}] {incident.title}",
            "body": f"{service.name} requires engineer review. Proposal {state['proposal_id']} awaits approval.",
        },
        "sent": False,
        "limitations": ["No external notification integration."],
    }
    return {"notification": record(state, "Notification", payload, [], start)}


def human_review(state):
    decision = interrupt(
        {"proposal_id": state["proposal_id"], "requires_role": "engineer", "executed": False}
    )
    return {"decision": decision}


def resolution_gate(state):
    if state["decision"]["decision"] != "approve":
        return {"resolution": {"status": "REJECTED_OR_REVISION_REQUIRED"}}
    resolution = interrupt(
        {
            "incident_id": state["incident_id"],
            "requires_actual_resolution": True,
            "requires_validation_events": True,
        }
    )
    return {"resolution": resolution}


def report(state):
    start = now()
    payload = {
        "incident_id": state["incident_id"],
        "rca": state["rca"],
        "decision": state["decision"],
        "actual_resolution": state["resolution"],
        "prevention_actions": ["Review service configuration and add missing metric monitoring."],
    }
    return {
        "report": record(
            state,
            "Incident Report",
            payload,
            [x for h in state["rca"]["hypotheses"] for x in h["supporting_event_ids"]],
            start,
        )
    }


ROOT.joinpath("storage").mkdir(exist_ok=True)
connection = sqlite3.connect(ROOT / "storage" / "workflow-checkpoints.sqlite", check_same_thread=False)
graph = StateGraph(State)
order = [
    "monitoring",
    "logs",
    "security",
    "rca",
    "runbook",
    "notification",
    "human_review",
    "resolution_gate",
    "report",
]
for name, node in zip(
    order, [monitoring, logs, security, rca, runbook, notification, human_review, resolution_gate, report]
):
    graph.add_node(name, node)
graph.add_edge(START, order[0])
for a, b in zip(order, order[1:]):
    graph.add_edge(a, b)
graph.add_edge(order[-1], END)
workflow = graph.compile(checkpointer=SqliteSaver(connection))
lock = threading.Lock()


def execute(run_id, resume=None):
    with lock:
        with Session() as db:
            run = db.get(Run, run_id)
            incident_id = run.incident_id
            if resume is None and run.status != "RUNNING":
                return
        try:
            result = workflow.invoke(
                Command(resume=resume)
                if resume is not None
                else {"run_id": run_id, "incident_id": incident_id},
                config={"configurable": {"thread_id": run_id}},
            )
            with Session() as db:
                run = db.get(Run, run_id)
                if "__interrupt__" in result:
                    payload = result["__interrupt__"][0].value
                    run.status = (
                        "WAITING_RESOLUTION"
                        if payload.get("requires_actual_resolution")
                        else "WAITING_APPROVAL"
                    )
                else:
                    run.status = "COMPLETED"
                run.completed_at = now()
                db.commit()
        except Exception as exc:
            with Session() as db:
                run = db.get(Run, run_id)
                run.status = "FAILED"
                run.error = str(exc)[:2000]
                run.completed_at = now()
                incident = db.get(Incident, incident_id)
                incident.status = "INVESTIGATING"
                timeline(
                    db, incident, "ANALYSIS_FAILED", "workflow", {"run_id": run_id, "error": str(exc)[:300]}
                )
                db.commit()
