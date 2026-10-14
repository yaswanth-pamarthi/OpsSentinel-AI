from datetime import datetime
from sqlalchemy import String, Float, Integer, Boolean, ForeignKey, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .core import Base, uid, now


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, unique=True)
    environment: Mapped[str] = mapped_column(String, default="demo")
    criticality: Mapped[str] = mapped_column(String, default="high")
    owner: Mapped[str] = mapped_column(String)
    dependencies_json: Mapped[list] = mapped_column(JSON, default=list)


class LogSource(Base):
    __tablename__ = "log_sources"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    parser_config: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Base):
    __tablename__ = "log_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    level: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    host: Mapped[str] = mapped_column(String, default="demo-host")
    source_type: Mapped[str] = mapped_column(String)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_line: Mapped[str] = mapped_column(String)
    original_timestamp: Mapped[str] = mapped_column(String)
    parse_status: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String, unique=True)


class Rule(Base):
    __tablename__ = "detection_rules"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, unique=True)
    query_type: Mapped[str] = mapped_column(String)
    pattern: Mapped[str] = mapped_column(String, default="")
    threshold: Mapped[float] = mapped_column(Float)
    window_seconds: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("detection_rules.id"))
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_count: Mapped[int] = mapped_column(Integer)
    dedupe_key: Mapped[str] = mapped_column(String, unique=True)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), unique=True)
    title: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="DETECTED")
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    commander_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_json: Mapped[dict] = mapped_column(JSON, default=dict)


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (UniqueConstraint("incident_id", "event_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("log_events.id"))
    relationship: Mapped[str] = mapped_column(String)
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Timeline(Base):
    __tablename__ = "timeline_entries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    type: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    actor: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict] = mapped_column(JSON)


class Run(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    workflow: Mapped[str] = mapped_column(String, default="incident-v1")
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    model: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Output(Base):
    __tablename__ = "agent_outputs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    agent_name: Mapped[str] = mapped_column(String)
    schema_version: Mapped[str] = mapped_column(String, default="1.0")
    prompt_version: Mapped[str] = mapped_column(String, default="grounded-v1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    inputs_json: Mapped[dict] = mapped_column(JSON)
    payload_json: Mapped[dict] = mapped_column(JSON)
    model_json: Mapped[dict] = mapped_column(JSON)


class Hypothesis(Base):
    __tablename__ = "rca_hypotheses"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    rank: Mapped[int] = mapped_column(Integer)
    cause: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String)


class Runbook(Base):
    __tablename__ = "runbooks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    title: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String, default="1.0")
    environment: Mapped[str] = mapped_column(String, default="demo")
    content: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="current")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    source_type: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String)
    section: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    embedding: Mapped[list] = mapped_column(Vector(768))


class Proposal(Base):
    __tablename__ = "remediation_proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), unique=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    payload_json: Mapped[dict] = mapped_column(JSON)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("remediation_proposals.id"), unique=True)
    engineer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IncidentReport(Base):
    __tablename__ = "incident_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    files_json: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
