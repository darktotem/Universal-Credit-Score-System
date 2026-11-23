from flask import g, has_request_context, request
from flask_jwt_extended import get_jwt, verify_jwt_in_request
from sqlalchemy import event

from extensions import db
from models.consumer import utcnow


class AuditImmutableError(Exception):
    """Raised on any attempt to update or delete an audit row."""


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    actor_kind = db.Column(db.String(20))      # "user" | "subscriber" | None (system)
    actor_id = db.Column(db.Integer)
    actor_role = db.Column(db.String(30))
    action = db.Column(db.String(60), nullable=False, index=True)
    resource_type = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.Integer)
    consumer_id = db.Column(db.Integer, index=True)  # the data subject, for per-consumer trails
    purpose = db.Column(db.String(50))
    ip_address = db.Column(db.String(45))
    details = db.Column(db.JSON)


@event.listens_for(AuditLog, "before_update")
def _block_update(mapper, connection, target):
    raise AuditImmutableError("Audit rows are append-only")


@event.listens_for(AuditLog, "before_delete")
def _block_delete(mapper, connection, target):
    raise AuditImmutableError("Audit rows are append-only")


def log_audit(action, resource_type, resource_id=None, consumer_id=None,
              details=None, commit=True):
    """
    Append one audit row. Actor, role, purpose and IP are taken from the current
    request automatically. Pass commit=False to write it in the same transaction
    as the change it describes.
    """
    kind = actor_id = role = None
    if has_request_context():
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
            if claims:
                kind, role = claims.get("kind"), claims.get("role")
                actor_id = int(claims["sub"])
        except Exception:
            pass  # unauthenticated or bad token: record as anonymous

    entry = AuditLog(
        actor_kind=kind,
        actor_id=actor_id,
        actor_role=role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        consumer_id=consumer_id,
        purpose=getattr(g, "purpose", None) if has_request_context() else None,
        ip_address=request.remote_addr if has_request_context() else None,
        details=details,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry
