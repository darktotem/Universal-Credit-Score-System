import re
from datetime import date
from decimal import Decimal

from marshmallow import ValidationError

MAX_BATCH_SIZE = 500
MAX_AMOUNT = Decimal("999999999999.99")
MAX_DAYS = 3650

_NID_STRIP = re.compile(r"[\s\-]")
_NID_VALID = re.compile(r"^[A-Z0-9]{6,20}$")
_REF_VALID = re.compile(r"^[A-Za-z0-9._\-/]{1,64}$")


def normalize_national_id(value):
    """Upper-case, strip spaces and hyphens, so '123-456 78' matches '12345678'."""
    return _NID_STRIP.sub("", value or "").upper()


def validate_national_id(value):
    if not _NID_VALID.match(normalize_national_id(value)):
        raise ValidationError("National ID must be 6-20 letters or digits")


def validate_external_ref(value):
    if not _REF_VALID.match(value or ""):
        raise ValidationError("external_ref must be 1-64 chars: letters, digits, . _ - /")


def validate_amount(value):
    if value < 0:
        raise ValidationError("Amount cannot be negative")
    if value > MAX_AMOUNT:
        raise ValidationError("Amount is too large")


def validate_days(value):
    if value < 0 or value > MAX_DAYS:
        raise ValidationError(f"Must be between 0 and {MAX_DAYS}")


def validate_not_future(value):
    if value > date.today():
        raise ValidationError("Date cannot be in the future")


def validate_batch_size(items):
    if not 1 <= len(items) <= MAX_BATCH_SIZE:
        raise ValidationError(f"Batch must contain 1 to {MAX_BATCH_SIZE} tradelines")