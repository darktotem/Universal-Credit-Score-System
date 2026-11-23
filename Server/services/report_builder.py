from datetime import timedelta

from extensions import db
from models import Subscriber
from models.consumer import ConsentGrant, utcnow
from models.inquiry import Inquiry
from services.scoring_engine import calculate_score
from utils.masking import filter_report

# purpose -> inquiry type. Only credit applications are hard inquiries.
HARD_PURPOSES = {"credit_application"}


def inquiry_type_for(purpose):
    return "hard" if purpose in HARD_PURPOSES else "soft"


def record_inquiry(consumer_id, subscriber_id, purpose, inquiry_type=None):
    """Dev 3's subscriber report pull calls this. Does NOT commit."""
    row = Inquiry(
        consumer_id=consumer_id,
        subscriber_id=subscriber_id,
        purpose=purpose,
        inquiry_type=inquiry_type or inquiry_type_for(purpose),
    )
    db.session.add(row)
    return row


def has_active_consent(consumer_id, subscriber_id, purpose):
    grants = db.session.query(ConsentGrant).filter_by(
        consumer_id=consumer_id, subscriber_id=subscriber_id, purpose=purpose
    ).all()
    return any(g.is_active for g in grants)


def consumer_dict(c):
    return {
        "id": c.id,
        "full_name": c.full_name,
        "national_id": c.national_id,
        "phone": c.phone,
        "date_of_birth": c.date_of_birth.isoformat() if c.date_of_birth else None,
        "address": c.address,
    }


def _tradeline_dicts(consumer_id):
    try:
        from models.tradeline import Tradeline  # owned by the ingestion dev
    except ImportError:
        return []
    rows = db.session.query(Tradeline).filter_by(consumer_id=consumer_id).all()
    names = {s.id: s.name for s in db.session.query(Subscriber).all()}
    keys = ["id", "subscriber_id", "account_type", "status", "original_amount",
            "outstanding_balance", "opened_at", "closed_at", "days_past_due",
            "worst_delinquency_days"]
    out = []
    for r in rows:
        d = {k: getattr(r, k, None) for k in keys}
        d["subscriber_name"] = names.get(d["subscriber_id"])
        for k in ("opened_at", "closed_at"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        out.append(d)
    return out


def _raw_tradelines(consumer_id):
    """Same rows as plain dicts with real date objects, for scoring."""
    try:
        from models.tradeline import Tradeline
    except ImportError:
        return []
    rows = db.session.query(Tradeline).filter_by(consumer_id=consumer_id).all()
    keys = ["status", "original_amount", "outstanding_balance", "opened_at",
            "days_past_due", "worst_delinquency_days", "account_type"]
    return [{k: getattr(r, k, None) for k in keys} for r in rows]


def build_report(consumer, viewer):
    """Assemble the full report, then filter it for who is looking."""
    cutoff = utcnow() - timedelta(days=365)
    inquiries = (db.session.query(Inquiry).filter_by(consumer_id=consumer.id)
                 .order_by(Inquiry.created_at.desc()).all())
    names = {s.id: s.name for s in db.session.query(Subscriber).all()}

    hard_12m = sum(1 for i in inquiries if i.inquiry_type == "hard" and i.created_at >= cutoff)
    soft_12m = sum(1 for i in inquiries if i.inquiry_type == "soft" and i.created_at >= cutoff)

    report = {
        "consumer": consumer_dict(consumer),
        "score": calculate_score(_raw_tradelines(consumer.id), hard_inquiries_12m=hard_12m),
        "tradelines": _tradeline_dicts(consumer.id),
        "inquiries": [{
            "id": i.id,
            "date": i.created_at.isoformat(),
            "type": i.inquiry_type,
            "purpose": i.purpose,
            "subscriber_name": names.get(i.subscriber_id, "Self (consumer)"),
        } for i in inquiries],
        "inquiry_summary": {"hard_12m": hard_12m, "soft_12m": soft_12m},
        "generated_at": utcnow().isoformat(),
    }
    return filter_report(report, viewer)