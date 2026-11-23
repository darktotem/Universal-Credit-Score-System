import os

from models import Subscriber, User
from services import auth_service
from extensions import db

SEED_PASSWORD = os.getenv("SEED_PASSWORD", "ChangeMe123!")

SEED_USERS = [
    ("admin@crb.local", "Bureau Admin", "admin"),
    ("analyst@crb.local", "Bureau Analyst", "analyst"),
    ("compliance@crb.local", "Compliance Officer", "compliance"),
    ("regulator@crb.local", "Regulator", "regulator"),
    ("consumer@crb.local", "Test Consumer", "consumer"),
]

SEED_SUBSCRIBERS = [
    ("Demo Bank", "premium", ["credit_application", "account_review", "collections"]),
    ("Demo SACCO", "standard", ["credit_application"]),
    ("Demo Telco", "basic", ["credit_application"]),
]


def seed():
    for email, name, role in SEED_USERS:
        if not db.session.query(User.id).filter_by(email=email).first():
            db.session.add(User(
                email=email,
                full_name=name,
                role=role,
                password_hash=auth_service.hash_password(SEED_PASSWORD),
                is_active=True,
            ))

    for name, tier, purposes in SEED_SUBSCRIBERS:
        if not db.session.query(Subscriber.id).filter_by(name=name).first():
            raw, prefix, key_hash = auth_service.generate_api_key()
            db.session.add(Subscriber(
                name=name, tier=tier, permissible_purposes=purposes,
                api_key_prefix=prefix, api_key_hash=key_hash, is_active=True,
            ))
            print(f"[seed] {name} API key (shown once): {raw}")

    db.session.commit()
    print("[seed] done")


if __name__ == "__main__":
    with create_app().app_context():
        seed()