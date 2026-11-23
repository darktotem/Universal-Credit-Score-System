from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt

from extensions import db
from models import Subscriber
from models.audit_log import AuditLog, log_audit
from models.consumer import ConsentGrant, Consumer, utcnow
from schemas.consumer_schema import ConsentGrantSchema, ConsumerProfileSchema
from services.ingestion_services import link_pending_tradelines
from services import report_builder
from utils.masking import viewer_from_claims
from utils.rbac import require_roles, require_self_or_roles

consumer_bp = Blueprint("consumers", __name__, url_prefix="/api/consumers")

STAFF = ("analyst", "compliance", "admin", "regulator")
AUDIT_ROLES = ("compliance", "admin", "regulator")


def _not_found(what="Consumer"):
    return jsonify(error="not_found", message=f"{what} not found"), 404


def _body():
    return request.get_json(silent=True) or {}


def _viewer(consumer_id):
    return viewer_from_claims(get_jwt(), consumer_id)


def _consent_dict(c):
    return {
        "id": c.id, "subscriber_id": c.subscriber_id, "purpose": c.purpose,
        "granted_at": c.granted_at.isoformat(),
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
        "active": c.is_active,
    }


# ---------- own profile ----------
@consumer_bp.get("/me")
@require_roles("consumer")
def my_profile():
    c = db.session.get(Consumer, int(get_jwt()["sub"]))
    if not c:
        return _not_found()
    return jsonify(report_builder.consumer_dict(c))


@consumer_bp.put("/me")
@require_roles("consumer")
def upsert_profile():
    data = ConsumerProfileSchema().load(_body())
    uid = int(get_jwt()["sub"])

    clash = db.session.query(Consumer.id).filter(
        Consumer.national_id == data["national_id"], Consumer.id != uid).first()
    if clash:
        return jsonify(error="conflict", message="National ID already registered"), 409

    c = db.session.get(Consumer, uid)
    created = c is None
    if created:
        c = Consumer(id=uid)
        db.session.add(c)
    for key, value in data.items():
        setattr(c, key, value)
        link_pending_tradelines(c)

    log_audit("consumer.profile_create" if created else "consumer.profile_update",
              "consumer", uid, consumer_id=uid, commit=False)
    db.session.commit()
    return jsonify(report_builder.consumer_dict(c)), 201 if created else 200


# ---------- report / score / inquiries ----------
@consumer_bp.get("/<int:consumer_id>/report")
@require_self_or_roles("consumer_id", *STAFF)
def get_report(consumer_id):
    c = db.session.get(Consumer, consumer_id)
    if not c:
        return _not_found()
    viewer = _viewer(consumer_id)
    report = report_builder.build_report(c, viewer)

    if viewer["is_self"]:  # consumer checking their own file = soft inquiry
        report_builder.record_inquiry(consumer_id, None, "self_check", "soft")

    log_audit("report.view", "credit_report", consumer_id, consumer_id=consumer_id,
              details={"viewer_role": viewer["role"], "self": viewer["is_self"]}, commit=False)
    db.session.commit()
    return jsonify(report)


@consumer_bp.get("/<int:consumer_id>/score")
@require_self_or_roles("consumer_id", *STAFF)
def get_score(consumer_id):
    c = db.session.get(Consumer, consumer_id)
    if not c:
        return _not_found()
    report = report_builder.build_report(c, _viewer(consumer_id))
    log_audit("score.view", "credit_score", consumer_id, consumer_id=consumer_id)
    return jsonify(report["score"])


@consumer_bp.get("/<int:consumer_id>/inquiries")
@require_self_or_roles("consumer_id", *STAFF)
def get_inquiries(consumer_id):
    c = db.session.get(Consumer, consumer_id)
    if not c:
        return _not_found()
    report = report_builder.build_report(c, _viewer(consumer_id))
    log_audit("inquiries.view", "inquiry", consumer_id, consumer_id=consumer_id)
    return jsonify(inquiries=report["inquiries"], summary=report["inquiry_summary"])


# ---------- consent ----------
def _only_self(consumer_id):
    claims = get_jwt()
    return claims.get("kind") == "user" and claims.get("sub") == str(consumer_id)


@consumer_bp.post("/<int:consumer_id>/consents")
@require_roles("consumer")
def grant_consent(consumer_id):
    if not _only_self(consumer_id):
        return jsonify(error="forbidden", message="You can only manage your own consents"), 403
    if not db.session.get(Consumer, consumer_id):
        return _not_found()
    data = ConsentGrantSchema().load(_body())
    if not db.session.get(Subscriber, data["subscriber_id"]):
        return _not_found("Subscriber")

    expires = data["expires_at"]
    if expires is not None and expires.tzinfo is not None:
        expires = expires.astimezone().replace(tzinfo=None)

    grant = ConsentGrant(consumer_id=consumer_id, subscriber_id=data["subscriber_id"],
                         purpose=data["purpose"], expires_at=expires)
    db.session.add(grant)
    db.session.flush()
    log_audit("consent.grant", "consent", grant.id, consumer_id=consumer_id,
              details={"subscriber_id": grant.subscriber_id, "purpose": grant.purpose},
              commit=False)
    db.session.commit()
    return jsonify(_consent_dict(grant)), 201


@consumer_bp.get("/<int:consumer_id>/consents")
@require_self_or_roles("consumer_id", *STAFF)
def list_consents(consumer_id):
    rows = (db.session.query(ConsentGrant).filter_by(consumer_id=consumer_id)
            .order_by(ConsentGrant.granted_at.desc()).all())
    return jsonify([_consent_dict(r) for r in rows])


@consumer_bp.delete("/<int:consumer_id>/consents/<int:consent_id>")
@require_roles("consumer")
def revoke_consent(consumer_id, consent_id):
    if not _only_self(consumer_id):
        return jsonify(error="forbidden", message="You can only manage your own consents"), 403
    grant = db.session.query(ConsentGrant).filter_by(id=consent_id, consumer_id=consumer_id).first()
    if not grant:
        return _not_found("Consent")
    grant.revoked_at = grant.revoked_at or utcnow()
    log_audit("consent.revoke", "consent", grant.id, consumer_id=consumer_id, commit=False)
    db.session.commit()
    return jsonify(_consent_dict(grant))


# ---------- audit trail for one consumer ----------
@consumer_bp.get("/<int:consumer_id>/audit")
@require_roles(*AUDIT_ROLES)
def consumer_audit(consumer_id):
    rows = (db.session.query(AuditLog).filter_by(consumer_id=consumer_id)
            .order_by(AuditLog.id.desc()).limit(200).all())
    return jsonify([{
        "id": r.id, "at": r.created_at.isoformat(), "action": r.action,
        "actor_kind": r.actor_kind, "actor_id": r.actor_id, "actor_role": r.actor_role,
        "purpose": r.purpose, "ip": r.ip_address, "details": r.details,
    } for r in rows])