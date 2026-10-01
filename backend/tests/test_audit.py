"""Test audit trail: event tertulis ke tabel audit_events."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import AuditEvent
from app.settings import get_settings


def test_audit_events_written_for_auth_and_workspace(client) -> None:  # noqa: ANN001
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "aud@x.com", "name": "Aud", "password": "password123"},
    )
    assert reg.status_code == 201
    headers = {"Authorization": f"Bearer {reg.json()['token']}"}

    ws = client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "Audit WS", "slug": "audit-ws"},
    )
    assert ws.status_code == 201

    engine = create_engine(get_settings().database_url)
    # Catatan: entity loading butuh Session.execute, bukan Connection.execute.
    session = sessionmaker(bind=engine)()
    try:
        actions = {
            row.action
            for row in session.execute(
                select(AuditEvent).where(AuditEvent.user_id.is_not(None))
            ).scalars()
        }
    finally:
        session.close()
    assert "auth.register" in actions
    assert "workspace.create" in actions
