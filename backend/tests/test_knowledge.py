from sqlalchemy import select
import pytest
from app.core import Session
from app.models import Service, KnowledgeChunk
from app import knowledge
from app.rca import proposal_from_knowledge


def test_complete_procedure_retrieval_preserves_all_sections(monkeypatch):
    with Session() as db:
        service = db.scalar(select(Service).where(Service.name == "checkout-api"))
        if not service:
            pytest.skip("Seed runbooks first")
        source = db.scalar(
            select(KnowledgeChunk).where(
                KnowledgeChunk.service_id == service.id, KnowledgeChunk.source_type == "runbook"
            )
        )
        assert source
        monkeypatch.setattr(knowledge, "embed", lambda texts: [list(source.embedding)])
        evidence = knowledge.retrieve(db, service, "known source", complete_runbook=True)
        assert {e["source_id"] for e in evidence} == {source.source_id}
        assert all(e["source_type"] == "runbook" for e in evidence)
        proposal = proposal_from_knowledge(evidence)
        assert all(
            proposal[section]
            for section in ["diagnostics", "immediate_containment", "permanent_fix", "rollback", "validation"]
        )
