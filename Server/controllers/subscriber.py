from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt

from extensions import db
from models.audit_log import log_audit
from models.consumer import Consumer
from models.subscriber import Subscriber
from schemas.subscriber_schema import ReportRequestSchema, TradelineBatchSchema
from services import ingestion_service, report_builder
from utils.masking import viewer_from_claims
from utils.rbac import require_permissible_purpose, require_roles, require_tier
from utils.validators import normalize_national_id

subscriber_bp = Blueprint("subscriber", __name__, url_prefix="/api/subscriber")

REPORT_PURPOSES = ("credit_application", "account_review", "collections")
CLEARANCE_PURPOSES = ("credit_application", "account_review")


def _body():
    return request.get_json(silent=True) or {}


def _current_subscriber():
    sub = db.session.get(Subscriber, int(get_jwt()["sub"]))
    return sub if sub and sub.is_active else None


def _inactive():
    return jsonify(error="forbidden", message="Subscriber account is inactive"), 403


def _no_consent():
    # Same answer for "unknown person" and "no consent": don't reveal who is in the bureau.
    return jsonify(error="not_found",
                   message="No consumer with active consent found for this ID and purpose"), 404


def _consented_consumer(sub):
    data = ReportRequestSchema().load(_body())
    consumer = db.session.query(Consumer).filter_by(
        national_id=normalize_national_id(data["national_id"])).first()
    if consumer and report_builder.has_active_consent(consumer.id, sub.id, g.purpose):
        return consumer
    log_audit("report.pull_denied", "credit_report", None,
              details={"subscriber_id": sub.id, "purpose": g.purpose})
    return None


@subscriber_bp.get("/me")
@require_roles("subscriber")
def me():
    sub = _current_subscriber()
    if not sub:
        return _inactive()
    return jsonify(id=sub.id, name=sub.name, subscriber_type=sub.subscriber_type,
                   tier=sub.tier, permissible_purposes=sub.permissible_purposes)


@subscriber_bp.post("/tradelines")
@require_roles("subscriber")
def ingest_tradelines():
    sub = _current_subscriber()
    if not sub:
        return _inactive()
    payload = TradelineBatchSchema().load(_body())
    result = ingestion_service.ingest_batch(sub, payload["tradelines"])
    accepted = result["created"] + result["updated"]
    return jsonify(result), (200 if accepted else 422)


@subscriber_bp.post("/reports/pull")
@require_permissible_purpose(*REPORT_PURPOSES)
@require_tier("standard")
def pull_report():
    sub = _current_subscriber()
    if not sub:
        return _inactive()
    consumer = _consented_consumer(sub)
    if not consumer:
        return _no_consent()

    viewer = viewer_from_claims(get_jwt(), consumer.id)
    report = report_builder.build_report(consumer, viewer)
    inquiry = report_builder.record_inquiry(consumer.id, sub.id, g.purpose)
    log_audit("report.pull", "credit_report", consumer.id, consumer_id=consumer.id,
              details={"subscriber_id": sub.id, "inquiry_type": inquiry.inquiry_type},
              commit=False)
    db.session.commit()
    return jsonify(report)


@subscriber_bp.post("/clearance")
@require_permissible_purpose(*CLEARANCE_PURPOSES)
@require_tier("basic")
def clearance():
    sub = _current_subscriber()
    if not sub:
        return _inactive()
    consumer = _consented_consumer(sub)
    if not consumer:
        return _no_consent()

    viewer = viewer_from_claims(get_jwt(), consumer.id)
    report = report_builder.build_report(consumer, viewer)
    decision = ingestion_service.clearance_from_report(report)
    inquiry = report_builder.record_inquiry(consumer.id, sub.id, g.purpose)
    log_audit("clearance.pull", "clearance", consumer.id, consumer_id=consumer.id,
              details={"subscriber_id": sub.id, "result": decision["result"],
                       "inquiry_type": inquiry.inquiry_type}, commit=False)
    db.session.commit()
    return jsonify(decision)