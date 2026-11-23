from datetime import date

from marshmallow import Schema, ValidationError, fields, validate, validates_schema

from models.subscriber import SUBSCRIBER_TYPES, TIERS
from models.tradeline import ACCOUNT_TYPES, TRADELINE_STATUSES
from schemas.consumer_schema import PURPOSES
from utils.validators import (
    validate_amount, validate_batch_size, validate_days, validate_external_ref,
    validate_national_id, validate_not_future,
)


class TradelineSchema(Schema):
    external_ref = fields.Str(required=True, validate=validate_external_ref)
    national_id = fields.Str(required=True, validate=validate_national_id)
    account_type = fields.Str(required=True, validate=validate.OneOf(ACCOUNT_TYPES))
    status = fields.Str(required=True, validate=validate.OneOf(TRADELINE_STATUSES))
    currency = fields.Str(load_default="KES", validate=validate.OneOf(["KES", "USD"]))
    original_amount = fields.Decimal(required=True, places=2, validate=validate_amount)
    outstanding_balance = fields.Decimal(required=True, places=2, validate=validate_amount)
    opened_at = fields.Date(required=True, validate=validate_not_future)
    closed_at = fields.Date(load_default=None, validate=validate_not_future)
    days_past_due = fields.Int(load_default=0, validate=validate_days)
    worst_delinquency_days = fields.Int(load_default=0, validate=validate_days)
    reported_at = fields.Date(load_default=date.today, validate=validate_not_future)

    @validates_schema
    def cross_field_rules(self, data, **kwargs):
        errors = {}
        if data.get("closed_at") and data["closed_at"] < data["opened_at"]:
            errors["closed_at"] = ["closed_at cannot be before opened_at"]
        if data["status"] == "closed":
            if data["outstanding_balance"] != 0:
                errors["outstanding_balance"] = ["A closed account must have a zero balance"]
            if not data.get("closed_at"):
                errors["closed_at"] = ["closed_at is required when status is closed"]
        if errors:
            raise ValidationError(errors)


class TradelineBatchSchema(Schema):
    """Envelope only. Each record is validated separately so one bad row doesn't sink the batch."""
    tradelines = fields.List(fields.Dict(), required=True, validate=validate_batch_size)


class ReportRequestSchema(Schema):
    national_id = fields.Str(required=True, validate=validate_national_id)


class SubscriberCreateSchema(Schema):
    """For the admin onboarding endpoint."""
    name = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    subscriber_type = fields.Str(required=True, validate=validate.OneOf(SUBSCRIBER_TYPES))
    tier = fields.Str(load_default="basic", validate=validate.OneOf(TIERS))
    permissible_purposes = fields.List(
        fields.Str(validate=validate.OneOf(PURPOSES)),
        required=True, validate=validate.Length(min=1),
    )