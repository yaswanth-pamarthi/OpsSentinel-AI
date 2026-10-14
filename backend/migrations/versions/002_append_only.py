from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE OR REPLACE FUNCTION reject_immutable_change() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Immutable evidence/timeline cannot be changed'; END; $$ LANGUAGE plpgsql"""
    )
    for table in ["timeline_entries", "incident_events"]:
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_immutable_change()"
        )


def downgrade():
    for table in ["timeline_entries", "incident_events"]:
        op.execute(f"DROP TRIGGER immutable_{table} ON {table}")
    op.execute("DROP FUNCTION reject_immutable_change()")
