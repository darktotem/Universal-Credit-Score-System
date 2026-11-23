import pytest

from extensions import db
from models import Subscriber
from models.audit_log import AuditImmutableError, AuditLog, log_audit


def actions():
    return [a.action for a in db.session.query(AuditLog).order_by(AuditLog.id).all()]


def test_profile_create_is_audited(crb_client, profile):
    row = db.session.query(AuditLog).filter_by(action="consumer.profile_create").one()
    assert row.consumer_id == profile["id"]
    assert row.actor_role == "consumer"


def test_report_view_logs_actor_role_and_subject(crb_client, profile, login_as):
    crb_client.get(f"/api/consumers/{profile['id']}/report", headers=login_as("analyst@crb.local"))
    row = db.session.query(AuditLog).filter_by(action="report.view").one()
    assert row.actor_role == "analyst"
    assert row.consumer_id == profile["id"]
    assert row.resource_type == "credit_report"


def test_consent_grant_and_revoke_are_audited(crb_client, profile):
    sub = db.session.query(Subscriber).filter_by(name="Demo Bank").one()
    base = f"/api/consumers/{profile['id']}/consents"
    r = crb_client.post(base, headers=profile["headers"],
                        json={"subscriber_id": sub.id, "purpose": "credit_application"})
    assert r.status_code == 201
    cid = r.get_json()["id"]
    assert crb_client.delete(f"{base}/{cid}", headers=profile["headers"]).status_code == 200
    assert "consent.grant" in actions() and "consent.revoke" in actions()


def test_audit_rows_cannot_be_updated(crb_app):
    row = log_audit("test.action", "thing", 1)
    row.action = "tampered"
    with pytest.raises(AuditImmutableError):
        db.session.commit()
    db.session.rollback()


def test_audit_rows_cannot_be_deleted(crb_app):
    row = log_audit("test.action", "thing", 1)
    db.session.delete(row)
    with pytest.raises(AuditImmutableError):
        db.session.commit()
    db.session.rollback()


def test_audit_trail_endpoint_roles(crb_client, profile, login_as):
    url = f"/api/consumers/{profile['id']}/audit"
    assert crb_client.get(url).status_code == 401
    assert crb_client.get(url, headers=login_as("consumer@crb.local")).status_code == 403
    assert crb_client.get(url, headers=login_as("analyst@crb.local")).status_code == 403
    r = crb_client.get(url, headers=login_as("compliance@crb.local"))
    assert r.status_code == 200
    assert any(e["action"] == "consumer.profile_create" for e in r.get_json())