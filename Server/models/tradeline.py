from extensions import db
from models.consumer import utcnow

ACCOUNT_TYPES = [
    "personal_loan", "credit_card", "mortgage", "student_loan",
    "overdraft", "asset_finance", "telco_postpaid",
]
TRADELINE_STATUSES = ["active", "closed", "defaulted", "written_off"]


class Tradeline(db.Model):
    """
    One lender-reported account. (subscriber_id, external_ref) is the upsert key.
    consumer_id is NULL until the person registers with the bureau; national_id is
    kept so the row can be linked later (see ingestion_service.link_pending_tradelines).
    consumer_id equals user.id (Consumer shares its primary key with User).
    """
    __tablename__ = "tradeline"

    id = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer, db.ForeignKey("subscriber.id"), nullable=False, index=True)
    consumer_id = db.Column(db.Integer, db.ForeignKey("consumer.id"), index=True)
    national_id = db.Column(db.String(32), nullable=False, index=True)
    external_ref = db.Column(db.String(64), nullable=False)

    account_type = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="KES")
    # asdecimal=False returns floats, which is what scoring_engine does its arithmetic with
    original_amount = db.Column(db.Numeric(14, 2, asdecimal=False), nullable=False)
    outstanding_balance = db.Column(db.Numeric(14, 2, asdecimal=False), nullable=False)
    opened_at = db.Column(db.Date, nullable=False)
    closed_at = db.Column(db.Date)
    days_past_due = db.Column(db.Integer, nullable=False, default=0)
    worst_delinquency_days = db.Column(db.Integer, nullable=False, default=0)
    reported_at = db.Column(db.Date, nullable=False)  # as-of date of the lender's data

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("subscriber_id", "external_ref", name="uq_tradeline_subscriber_ref"),
    )