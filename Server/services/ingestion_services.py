from marshmallow import ValidationError

from extensions import db
from models.audit_log import log_audit
from models.consumer import Consumer
from models.subscriber import Subscriber
from models.tradeline import Tradeline
from schemas.subscriber_schema import TradelineSchema
from services import auth_service
from utils.validators import normalize_national_id

UPDATABLE_FIELDS = [
    "account_type", "status", "currency", "original_amount", "outstanding_balance",
    "opened_at", "closed_at", "days_past_due", "worst_delinquency_days", "reported_at",
]


def _prepare(data):
    d = dict(data)
    d["national_id"] = normalize_national_id(d["national_id"])
    d["original_amount"] = float(d["original_amount"])
    d["outstanding_balance"] = float(d["outstanding_balance"])
    d["worst_delinquency_days"] = max(d["worst_delinquency_days"], d["days_past_due"])
    return d


def _reject(rejected, idx, ref, field, message):
    rejected.append({"index": idx, "external_ref": ref, "errors": {field: [message]}})


def ingest_batch(subscriber, raw_records):
    """
    Validate and upsert a batch of tradelines for one subscriber, in one transaction.
    Valid rows are saved even if others are rejected. Returns a summary dict.
    """
    schema = TradelineSchema()
    rejected, valid, seen = [], [], set()

    for idx, raw in enumerate(raw_records):
        ref = raw.get("external_ref") if isinstance(raw.get("external_ref"), str) else None
        try:
            data = schema.load(raw)
        except ValidationError as err:
            rejected.append({"index": idx, "external_ref": ref, "errors": err.messages})
            continue
        if data["external_ref"] in seen:
            _reject(rejected, idx, ref, "external_ref", "Duplicate external_ref in this batch")
            continue
        seen.add(data["external_ref"])
        valid.append((idx, _prepare(data)))

    refs = [d["external_ref"] for _, d in valid]
    nids = {d["national_id"] for _, d in valid}
    existing = {}
    consumers = {}
    if refs:
        existing = {
            t.external_ref: t for t in db.session.query(Tradeline).filter(
                Tradeline.subscriber_id == subscriber.id, Tradeline.external_ref.in_(refs))
        }
        consumers = {
            c.national_id: c.id for c in db.session.query(Consumer).filter(
                Consumer.national_id.in_(nids))
        }

    created = updated = pending_link = 0
    for idx, d in valid:
        row = existing.get(d["external_ref"])
        consumer_id = consumers.get(d["national_id"])

        if row is None:
            db.session.add(Tradeline(subscriber_id=subscriber.id, consumer_id=consumer_id, **d))
            created += 1
        else:
            if row.national_id != d["national_id"]:
                _reject(rejected, idx, d["external_ref"], "national_id",
                        "An existing account cannot change owner")
                continue
            if d["reported_at"] < row.reported_at:
                _reject(rejected, idx, d["external_ref"], "reported_at",
                        "Stale report: we already hold newer data for this account")
                continue
            for field in UPDATABLE_FIELDS:
                setattr(row, field, d[field])
            row.consumer_id = row.consumer_id or consumer_id
            updated += 1

        if consumer_id is None and (row is None or row.consumer_id is None):
            pending_link += 1

    log_audit("tradeline.ingest", "tradeline", None,
              details={"subscriber_id": subscriber.id, "received": len(raw_records),
                       "created": created, "updated": updated, "rejected": len(rejected)},
              commit=False)
    db.session.commit()

    rejected.sort(key=lambda r: r["index"])
    return {"received": len(raw_records), "created": created, "updated": updated,
            "pending_link": pending_link, "rejected": rejected}


def link_pending_tradelines(consumer):
    """
    Attach tradelines that lenders reported before this person registered.
    Call when a Consumer profile is first created. Does NOT commit.
    """
    return (db.session.query(Tradeline)
            .filter(Tradeline.consumer_id.is_(None), Tradeline.national_id == consumer.national_id)
            .update({Tradeline.consumer_id: consumer.id}, synchronize_session=False))


def clearance_from_report(report):
    """Reduce an already-filtered report to a lightweight clearance decision (no numeric score)."""
    tradelines = report["tradelines"]
    active = [t for t in tradelines if t["status"] == "active"]
    flags = []
    if any(t["status"] in ("defaulted", "written_off") for t in tradelines):
        flags.append("defaulted_account")
    if any((t["days_past_due"] or 0) >= 60 for t in active):
        flags.append("seriously_delinquent")
    elif any((t["days_past_due"] or 0) >= 30 for t in active):
        flags.append("recent_delinquency")

    if not tradelines:
        result = "no_history"
    elif "defaulted_account" in flags or "seriously_delinquent" in flags:
        result = "adverse"
    elif flags:
        result = "caution"
    else:
        result = "clear"
    return {"result": result, "flags": flags, "band": report["score"]["band"]}


# ---------- onboarding helpers for the admin controller ----------
def onboard_subscriber(name, subscriber_type, tier, purposes):
    """Returns (subscriber, raw_api_key). The raw key is shown once and never stored."""
    if db.session.query(Subscriber.id).filter_by(name=name).first():
        raise ValueError("A subscriber with this name already exists")
    raw, prefix, key_hash = auth_service.generate_api_key()
    sub = Subscriber(name=name, subscriber_type=subscriber_type, tier=tier,
                     permissible_purposes=list(purposes),
                     api_key_prefix=prefix, api_key_hash=key_hash, is_active=True)
    db.session.add(sub)
    db.session.flush()
    log_audit("subscriber.onboard", "subscriber", sub.id,
              details={"name": name, "tier": tier, "purposes": list(purposes)}, commit=False)
    db.session.commit()
    return sub, raw


def rotate_api_key(subscriber):
    raw, prefix, key_hash = auth_service.generate_api_key()
    subscriber.api_key_prefix, subscriber.api_key_hash = prefix, key_hash
    log_audit("subscriber.key_rotate", "subscriber", subscriber.id, commit=False)
    db.session.commit()
    return raw