import io, json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from pypdf import PdfReader
from .core import (
    Session,
    session,
    current_user,
    roles,
    login,
    seed_users,
    settings,
    get,
    dump,
    audit,
    ROOT,
    now,
)
from datetime import datetime
from .models import (
    Service,
    LogSource,
    Event,
    Rule,
    Alert,
    Incident,
    IncidentEvent,
    Timeline,
    Hypothesis,
    Proposal,
    Run,
    Output,
    Approval,
    Runbook,
    IncidentReport,
)
from .schemas import (
    Login,
    ServiceIn,
    SourceIn,
    PasteIn,
    EventsIn,
    RuleIn,
    EvaluateIn,
    SeverityIn,
    StatusIn,
    DecisionIn,
    ResolutionIn,
    KnowledgeIn,
)
from .ingestion import ingest, signature, redact
from .detection import evaluate, timeline
from .knowledge import add_knowledge, retrieve
from .workflows import execute
from .reports import make_report


@asynccontextmanager
async def lifespan(app):
    with Session() as db:
        seed_users(db, ["engineer", "commander", "viewer"])
    yield


app = FastAPI(title="OpsSentinel AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)
operator = roles("engineer", "commander")
engineer = roles("engineer")
commander = roles("commander")


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Record already exists or conflicts with a reference")


@app.get("/health")
def health(db=Depends(session)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "postgresql",
        "ai_mode": settings.ai_mode,
        "model": settings.ollama_chat_model,
    }


@app.post("/auth/login")
def authenticate(body: Login, db=Depends(session)):
    return login(db, body.email, body.password)


@app.get("/services")
def services(user=Depends(current_user), db=Depends(session)):
    return [dump(s) for s in db.scalars(select(Service))]


@app.post("/services")
def add_service(body: ServiceIn, user=Depends(operator), db=Depends(session)):
    s = Service(**body.model_dump())
    db.add(s)
    db.flush()
    audit(db, user, "CREATE_SERVICE", s.id)
    commit(db)
    return dump(s)


@app.patch("/services/{id}")
def edit_service(id: str, body: ServiceIn, user=Depends(commander), db=Depends(session)):
    s = get(db, Service, id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    audit(db, user, "UPDATE_SERVICE", id)
    commit(db)
    return dump(s)


@app.get("/log-sources")
def sources(user=Depends(operator), db=Depends(session)):
    return [dump(s) for s in db.scalars(select(LogSource))]


@app.post("/log-sources")
def add_source(body: SourceIn, user=Depends(engineer), db=Depends(session)):
    get(db, Service, body.service_id)
    s = LogSource(**body.model_dump())
    db.add(s)
    commit(db)
    return dump(s)


@app.post("/logs/paste")
def paste(body: PasteIn, user=Depends(engineer), db=Depends(session)):
    result = ingest(db, body.text.splitlines(), body.service)
    audit(db, user, "INGEST_PASTE", body.service, result)
    commit(db)
    return result


@app.post("/logs/events")
def events(body: EventsIn, user=Depends(engineer), db=Depends(session)):
    result = ingest(db, [json.dumps(e) for e in body.events], body.service)
    audit(db, user, "INGEST_EVENTS", body.service, result)
    commit(db)
    return result


@app.post("/logs/upload")
async def upload(
    file: UploadFile = File(...),
    service: str = Form("checkout-api"),
    user=Depends(engineer),
    db=Depends(session),
):
    if Path(file.filename or "").suffix.lower() not in (".log", ".txt", ".jsonl", ".json"):
        raise HTTPException(415, "Accepted extensions: .log .txt .jsonl .json")
    if file.content_type not in (
        "text/plain",
        "application/json",
        "application/octet-stream",
        "application/x-ndjson",
    ):
        raise HTTPException(415, "Unsupported MIME type")
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Maximum 10 MB")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "Logs must be UTF-8 text")
    if content.lstrip().startswith("["):
        try:
            lines = [json.dumps(item) for item in json.loads(content)]
        except ValueError:
            raise HTTPException(422, "Invalid JSON array")
    else:
        lines = content.splitlines()
    result = ingest(db, lines, service)
    audit(db, user, "INGEST_FILE", service, result)
    commit(db)
    return result


@app.get("/logs/search")
def search(
    service_id: str | None = None,
    level: str | None = None,
    q: str = "",
    trace_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(operator),
    db=Depends(session),
):
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(422, "Pagination limit must be 1..500")
    query = select(Event)
    if service_id:
        query = query.where(Event.service_id == service_id)
    if level:
        query = query.where(Event.level == level.upper())
    if q:
        query = query.where(Event.message.ilike("%" + q + "%"))
    if trace_id:
        query = query.where(Event.trace_id == trace_id)
    if start:
        query = query.where(Event.timestamp >= start)
    if end:
        query = query.where(Event.timestamp <= end)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Event.timestamp.desc()).offset(offset).limit(limit)).all()
    groups = {}
    for e in rows:
        key = signature(e.message)
        groups[key] = groups.get(key, 0) + 1
    return {"total": total, "events": [dump(e) for e in rows], "groups": groups}


@app.get("/rules")
def rules(user=Depends(current_user), db=Depends(session)):
    return [dump(r) for r in db.scalars(select(Rule))]


@app.post("/rules")
def add_rule(body: RuleIn, user=Depends(commander), db=Depends(session)):
    rule = Rule(**body.model_dump())
    db.add(rule)
    db.flush()
    audit(db, user, "CREATE_RULE", rule.id)
    commit(db)
    return dump(rule)


@app.patch("/rules/{id}")
def edit_rule(id: str, body: RuleIn, user=Depends(commander), db=Depends(session)):
    rule = get(db, Rule, id)
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    audit(db, user, "UPDATE_RULE", id)
    commit(db)
    return dump(rule)


@app.post("/rules/evaluate")
def evaluate_rules(body: EvaluateIn, user=Depends(engineer), db=Depends(session)):
    if body.service_id:
        get(db, Service, body.service_id)
    if body.start and body.end and body.start > body.end:
        raise HTTPException(422, "Start must precede end")
    result = evaluate(db, body.service_id, body.start, body.end, user.id)
    audit(db, user, "EVALUATE_RULES", "rules", result)
    commit(db)
    return result


@app.get("/alerts")
def alerts(user=Depends(current_user), db=Depends(session)):
    return [dump(a) for a in db.scalars(select(Alert).order_by(Alert.window_end.desc()).limit(200))]


@app.get("/incidents")
def incidents(user=Depends(current_user), db=Depends(session)):
    return [
        {**dump(i), "service": db.get(Service, i.service_id).name}
        for i in db.scalars(select(Incident).order_by(Incident.detected_at.desc()))
    ]


@app.get("/incidents/{id}")
def detail(id: str, user=Depends(current_user), db=Depends(session)):
    i = get(db, Incident, id)
    return {
        **dump(i),
        "service": dump(db.get(Service, i.service_id)),
        "evidence": [
            dump(e) for e in db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == id))
        ],
        "timeline": [
            dump(t)
            for t in db.scalars(
                select(Timeline).where(Timeline.incident_id == id).order_by(Timeline.timestamp)
            )
        ],
        "hypotheses": [
            dump(h)
            for h in db.scalars(
                select(Hypothesis).where(Hypothesis.incident_id == id).order_by(Hypothesis.rank)
            )
        ],
        "proposals": [dump(p) for p in db.scalars(select(Proposal).where(Proposal.incident_id == id))],
        "runs": [
            dump(r)
            for r in db.scalars(select(Run).where(Run.incident_id == id).order_by(Run.started_at.desc()))
        ],
    }


@app.patch("/incidents/{id}/severity")
def severity(id: str, body: SeverityIn, user=Depends(commander), db=Depends(session)):
    i = get(db, Incident, id)
    old = i.severity
    i.severity = body.severity
    i.commander_id = user.id
    timeline(db, i, "SEVERITY_CHANGED", user.id, {"before": old, **body.model_dump()})
    commit(db)
    return dump(i)


@app.patch("/incidents/{id}/status")
def status(id: str, body: StatusIn, user=Depends(commander), db=Depends(session)):
    i = get(db, Incident, id)
    valid = (
        (body.status == "CLOSED" and i.status == "RESOLVED" and i.resolution_json.get("validation_event_ids"))
        or (body.status == "FALSE_POSITIVE" and i.status == "INVESTIGATING")
        or (body.status == "INVESTIGATING" and i.status in ("DETECTED", "RESOLVED", "REMEDIATION_PROPOSED"))
    )
    if not valid:
        raise HTTPException(409, "Invalid transition or missing resolution validation")
    if body.status == "CLOSED":
        latest = db.scalar(select(Run).where(Run.incident_id == id).order_by(Run.started_at.desc()))
        if not latest or latest.status != "COMPLETED":
            raise HTTPException(409, "Report agent must complete before closure")
    i.status = body.status
    timeline(db, i, body.status, user.id, {"reason": body.reason})
    audit(db, user, "INCIDENT_STATUS", id, body.model_dump())
    commit(db)
    return dump(i)


@app.post("/incidents/{id}/analysis-runs")
def analyze_incident(id: str, tasks: BackgroundTasks, user=Depends(engineer), db=Depends(session)):
    i = get(db, Incident, id)
    if i.status not in ("DETECTED", "INVESTIGATING"):
        raise HTTPException(409, "Incident is not ready for analysis")
    active = db.scalar(
        select(Run).where(
            Run.incident_id == id, Run.status.in_(["RUNNING", "WAITING_APPROVAL", "WAITING_RESOLUTION"])
        )
    )
    if active:
        raise HTTPException(409, "Active analysis already exists")
    run = Run(incident_id=id, model=settings.ollama_chat_model)
    db.add(run)
    db.flush()
    i.status = "INVESTIGATING"
    timeline(db, i, "ANALYSIS_STARTED", user.id, {"run_id": run.id})
    audit(db, user, "START_ANALYSIS", run.id)
    commit(db)
    tasks.add_task(execute, run.id)
    return dump(run)


@app.get("/analysis-runs/{id}")
def run_detail(id: str, user=Depends(current_user), db=Depends(session)):
    run = get(db, Run, id)
    return {
        **dump(run),
        "outputs": [
            dump(o) for o in db.scalars(select(Output).where(Output.run_id == id).order_by(Output.started_at))
        ],
    }


@app.post("/proposals/{id}/decision")
def decision(id: str, body: DecisionIn, tasks: BackgroundTasks, user=Depends(operator), db=Depends(session)):
    p = get(db, Proposal, id)
    run = get(db, Run, p.run_id)
    if p.status != "PENDING" or run.status != "WAITING_APPROVAL":
        raise HTTPException(409, "Proposal is not waiting for approval")
    if body.decision == "approve" and (
        not all(
            p.payload_json.get(section)
            for section in ("diagnostics", "immediate_containment", "permanent_fix", "rollback", "validation")
        )
        or p.payload_json.get("warnings")
    ):
        raise HTTPException(
            409,
            "Approval requires a current complete runbook with diagnostics, containment, fix, rollback and validation; request revision instead",
        )
    p.status = {"approve": "APPROVED", "reject": "REJECTED", "revise": "REVISION_REQUIRED"}[body.decision]
    i = get(db, Incident, p.incident_id)
    if body.decision != "approve":
        i.status = "INVESTIGATING"
    db.add(Approval(proposal_id=id, engineer_id=user.id, decision=body.decision, reason=body.reason))
    timeline(
        db, i, "PROPOSAL_" + p.status, user.id, {**body.model_dump(), "proposal_id": id, "executed": False}
    )
    audit(db, user, "PROPOSAL_DECISION", id, body.model_dump())
    commit(db)
    tasks.add_task(execute, run.id, {**body.model_dump(), "actor_id": user.id})
    return dump(p)


@app.post("/incidents/{id}/resolve")
def resolve(id: str, body: ResolutionIn, tasks: BackgroundTasks, user=Depends(engineer), db=Depends(session)):
    i = get(db, Incident, id)
    run = db.scalar(
        select(Run)
        .where(Run.incident_id == id, Run.status == "WAITING_RESOLUTION")
        .order_by(Run.started_at.desc())
    )
    if i.status != "REMEDIATION_PROPOSED" or not run:
        raise HTTPException(409, "Approved proposal and waiting-resolution workflow required")
    p = db.scalar(select(Proposal).where(Proposal.run_id == run.id, Proposal.status == "APPROVED"))
    if not p:
        raise HTTPException(409, "Engineer approval is required")
    events = db.scalars(
        select(Event).where(
            Event.id.in_(body.validation_event_ids),
            Event.service_id == i.service_id,
            Event.timestamp > i.detected_at,
        )
    ).all()
    if len(events) != len(set(body.validation_event_ids)) or any(
        e.level in ("ERROR", "CRITICAL") or float(e.attributes.get("http_status", 0)) >= 500 for e in events
    ):
        raise HTTPException(
            422, "Validation must cite existing post-detection recovery events for this service"
        )
    first = min(e.timestamp for e in events)
    last = max(e.timestamp for e in events)
    if (last - first).total_seconds() < 600:
        raise HTTPException(
            422, "Recovery evidence must span at least ten minutes; generate the 20-minute scenario"
        )
    window = db.scalars(
        select(Event).where(
            Event.service_id == i.service_id, Event.timestamp >= first, Event.timestamp <= last
        )
    ).all()
    failures = [
        e
        for e in window
        if e.level in ("ERROR", "CRITICAL") or float(e.attributes.get("http_status", 0)) >= 500
    ]
    error_rate = len(failures) / len(window) if window else 1
    latency = sorted(float(e.attributes["latency_ms"]) for e in window if "latency_ms" in e.attributes)
    p95 = latency[max(0, __import__("math").ceil(0.95 * len(latency)) - 1)] if latency else None
    if len(window) < 20 or error_rate >= 0.01 or (p95 is not None and p95 > 2000):
        raise HTTPException(
            422,
            "Recovery window must contain at least 20 events, error rate below 1% and p95 latency at or below 2000 ms",
        )
    i.resolution_json = {
        **body.model_dump(),
        "actor_id": user.id,
        "recorded_at": now().isoformat(),
        "validation_metrics": {
            "window_start": first.isoformat(),
            "window_end": last.isoformat(),
            "window_seconds": (last - first).total_seconds(),
            "event_count": len(window),
            "error_rate": error_rate,
            "p95_latency_ms": p95,
        },
    }
    i.status = "RESOLVED"
    # The software never sets proposal.executed: actual execution is a separately recorded human action.
    timeline(db, i, "RESOLVED", user.id, i.resolution_json)
    audit(db, user, "RECORD_RESOLUTION", id)
    commit(db)
    tasks.add_task(execute, run.id, i.resolution_json)
    return dump(i)


@app.get("/runbooks")
def runbooks(user=Depends(current_user), db=Depends(session)):
    return [dump(b) for b in db.scalars(select(Runbook))]


@app.post("/runbooks")
def add_runbook(body: KnowledgeIn, user=Depends(engineer), db=Depends(session)):
    get(db, Service, body.service_id)
    book = add_knowledge(db, body.model_dump())
    audit(db, user, "ADD_RUNBOOK", book.id)
    commit(db)
    return dump(book)


@app.post("/knowledge/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    service_id: str = Form(...),
    title: str = Form(...),
    version: str = Form("1.0"),
    user=Depends(engineer),
    db=Depends(session),
):
    s = get(db, Service, service_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".md", ".txt", ".pdf"):
        raise HTTPException(415, "Knowledge must be Markdown, text or digital PDF")
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Maximum 10 MB")
    try:
        content = (
            "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
            if suffix == ".pdf"
            else data.decode("utf-8-sig")
        )
    except Exception:
        raise HTTPException(422, "Unreadable knowledge document")
    body = KnowledgeIn(
        service_id=s.id, title=title, version=version, environment=s.environment, content=redact(content)
    )
    book = add_knowledge(db, body.model_dump())
    return dump(book)


@app.get("/knowledge/search")
def knowledge_search(service_id: str, q: str, user=Depends(current_user), db=Depends(session)):
    return retrieve(db, get(db, Service, service_id), q)


@app.post("/incidents/{id}/report")
def report(id: str, user=Depends(commander), db=Depends(session)):
    i = get(db, Incident, id)
    if i.status != "CLOSED":
        raise HTTPException(409, "Incident must be closed with validated resolution before final report")
    existing = db.scalar(select(IncidentReport).where(IncidentReport.incident_id == id))
    if existing:
        return dump(existing)
    run = db.scalar(
        select(Run).where(Run.incident_id == id, Run.status == "COMPLETED").order_by(Run.started_at.desc())
    )
    if not run:
        raise HTTPException(409, "Complete incident workflow first")
    payload = {
        "incident": dump(i),
        "impact": i.title,
        "actual_resolution": i.resolution_json,
        "immutable_timeline": [
            dump(t)
            for t in db.scalars(
                select(Timeline).where(Timeline.incident_id == id).order_by(Timeline.timestamp)
            )
        ],
        "agent_outputs": [dump(o) for o in db.scalars(select(Output).where(Output.run_id == run.id))],
        "prevention_actions": ["Add pool/session metrics and regression alerts."],
        "limitations": ["Local synthetic telemetry; causal hypotheses are not calibrated probabilities."],
    }
    files = make_report("OpsSentinel-" + id, payload)
    record = IncidentReport(incident_id=id, run_id=run.id, files_json=files)
    db.add(record)
    db.flush()
    service = db.get(Service, i.service_id)
    add_knowledge(
        db,
        {
            "service_id": service.id,
            "title": i.title,
            "version": "1",
            "environment": service.environment,
            "content": "# Resolved incident\n" + i.title + "\n" + json.dumps(i.resolution_json),
        },
        source_type="incident_report",
        source_id=record.id,
    )
    audit(db, user, "GENERATE_INCIDENT_REPORT", id)
    commit(db)
    return dump(record)


@app.get("/reports/{id}/{format}")
def download_report(id: str, format: str, user=Depends(current_user), db=Depends(session)):
    r = get(db, IncidentReport, id)
    if format not in r.files_json:
        raise HTTPException(404, "Unknown report format")
    path = ROOT / "storage" / "reports" / r.files_json[format]
    return FileResponse(path, filename=path.name)
