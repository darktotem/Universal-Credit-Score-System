from marshmallow import Schema, fields, validate, post_load
from utils.validators import normalize_national_id, validate_national_id

PURPOSES = ["credit_application", "account_review", "collections"]

national_id = fields.Str(required=True, validate=validate_national_id)

@post_load
def _normalize(self, data, **kwargs):
    data["national_id"] = normalize_national_id(data["national_id"])
    return data

class ConsumerProfileSchema(Schema):
    full_name = fields.Str(required=True, validate=validate.Length(min=1, max=120))
    national_id = fields.Str(required=True, validate=validate.Length(min=6, max=32))
    phone = fields.Str(load_default=None, validate=validate.Length(max=20))
    date_of_birth = fields.Date(load_default=None)
    address = fields.Str(load_default=None, validate=validate.Length(max=255))


class ConsentGrantSchema(Schema):
    subscriber_id = fields.Int(required=True)
    purpose = fields.Str(required=True, validate=validate.OneOf(PURPOSES))
    expires_at = fields.DateTime(load_default=None)