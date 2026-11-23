from extensions import db
from models.consumer import utcnow


class Inquiry(db.Model):
    """
    hard = tied to a credit application, visible to other lenders, counts in the score.
    soft = account review / self-check, never shown to other lenders, never scored.
    subscriber_id NULL means the consumer checked their own report.
    """
    __tablename__ = "inquiry"

    id = db.Column(db.Integer, primary_key=True)
    consumer_id = db.Column(db.Integer, db.ForeignKey("consumer.id"), nullable=False)
    subscriber_id = db.Column(db.Integer, db.ForeignKey("subscriber.id"))
    purpose = db.Column(db.String(50), nullable=False)
    inquiry_type = db.Column(db.String(10), nullable=False)  # "hard" | "soft"
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.Index("ix_inquiry_consumer_created", "consumer_id", "created_at"),)