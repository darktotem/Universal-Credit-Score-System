import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from flask_jwt_extended import create_access_token, create_refresh_token
from werkzeug.security import check_password_hash, generate_password_hash

from models import RevokedToken, Subscriber, User
from extensions import db

CONSUMER = "consumer"
KEY_PREFIX_LEN = 8


class AuthError(Exception):
    def __init__(self, message, status=401):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------- hashing ----------
def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def _hash_key(raw_key: str) -> str:
    # API keys are high-entropy random strings, so a plain SHA-256 is appropriate.
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key():
    """Returns (raw_key, prefix, key_hash). Show raw_key once, store only prefix + hash."""
    prefix = secrets.token_hex(KEY_PREFIX_LEN // 2)
    raw_key = f"crb_{prefix}_{secrets.token_urlsafe(32)}"
    return raw_key, prefix, _hash_key(raw_key)


# ---------- consumers / staff ----------
def user_public(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
    }


def register_consumer(email, password, full_name) -> User:
    email = email.lower().strip()
    if db.session.query(User.id).filter_by(email=email).first():
        raise AuthError("Email already registered", 409)
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=CONSUMER,  # self-registration can never create staff
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def authenticate_user(email, password) -> User:
    user = db.session.query(User).filter_by(email=email.lower().strip()).first()
    # same message for unknown email / wrong password / inactive: no account enumeration
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError("Invalid credentials", 401)
    return user


def issue_user_tokens(user: User) -> dict:
    claims = {"kind": "user", "role": user.role}
    return {
        "access_token": create_access_token(identity=str(user.id), additional_claims=claims),
        "refresh_token": create_refresh_token(identity=str(user.id), additional_claims=claims),
    }


def refresh_user_token(user_id: int) -> dict:
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        raise AuthError("Account disabled", 401)
    claims = {"kind": "user", "role": user.role}
    return {"access_token": create_access_token(identity=str(user.id), additional_claims=claims)}


# ---------- subscribers ----------
def authenticate_subscriber(raw_key: str) -> Subscriber:
    if not raw_key or not raw_key.startswith("crb_"):
        raise AuthError("Invalid API key", 401)
    parts = raw_key.split("_", 2)
    if len(parts) != 3:
        raise AuthError("Invalid API key", 401)
    sub = db.session.query(Subscriber).filter_by(api_key_prefix=parts[1]).first()
    if (
        not sub
        or not sub.is_active
        or not hmac.compare_digest(sub.api_key_hash, _hash_key(raw_key))
    ):
        raise AuthError("Invalid API key", 401)
    return sub


def issue_subscriber_token(sub: Subscriber) -> dict:
    claims = {
        "kind": "subscriber",
        "role": "subscriber",
        "tier": sub.tier,
        "purposes": list(sub.permissible_purposes or []),
    }
    return {"access_token": create_access_token(identity=str(sub.id), additional_claims=claims)}


# ---------- logout ----------
def revoke_token(jwt_payload: dict) -> None:
    exp = datetime.fromtimestamp(jwt_payload["exp"], tz=timezone.utc)
    db.session.add(RevokedToken(jti=jwt_payload["jti"], expires_at=exp))
    db.session.commit()