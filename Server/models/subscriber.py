from extensions import db
from models.consumer import utcnow

SUBSCRIBER_TYPES = ["bank", "sacco", "student_loan_board", "digital_lender", "telco"]
TIERS = ["basic", "standard", "premium"]


class Subscriber(db.Model):
    __tablename__ = "subscriber"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    subscriber_type = db.Column(db.String(30))  # nullable: seed.py doesn't set it
    tier = db.Column(db.String(20), nullable=False, default="basic")
    api_key_prefix = db.Column(db.String(16), unique=True, nullable=False, index=True)
    api_key_hash = db.Column(db.String(64), nullable=False)
    permissible_purposes = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    