from datetime import datetime, timezone

from extensions import db


def utcnow():
    """Naive UTC, so values compare cleanly on both SQLite and PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Consumer(db.Model):
    __tablename__ = "consumer"

    # Shared primary key with User: consumer.id == user.id
    id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    national_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date)
    address = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ConsentGrant(db.Model):
    __tablename__ = "consent_grant"

    id = db.Column(db.Integer, primary_key=True)
    consumer_id = db.Column(db.Integer, db.ForeignKey("consumer.id"), nullable=False, index=True)
    subscriber_id = db.Column(db.Integer, db.ForeignKey("subscriber.id"), nullable=False, index=True)
    purpose = db.Column(db.String(50), nullable=False)
    granted_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)

    @property
    def is_active(self):
        now = utcnow()
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)