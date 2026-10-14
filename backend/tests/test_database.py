import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from app.core import Session
from app.models import Timeline, IncidentEvent


@pytest.mark.parametrize("model,table", [(Timeline, "timeline_entries"), (IncidentEvent, "incident_events")])
def test_frozen_evidence_and_timeline_database_guard(model, table):
    with Session() as db:
        record = db.scalar(select(model))
        if not record:
            pytest.skip("Run the prepared incident first")
        with pytest.raises(DBAPIError):
            db.execute(text(f"UPDATE {table} SET id=id WHERE id=:id"), {"id": record.id})
        db.rollback()
