import pytest

from app import create_app
from config import TestConfig
from extensions import db
from models import Subscriber
from seed import seed
from services import auth_service

PASSWORD = "ChangeMe123!"


@pytest.fixture()
def crb_app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        seed()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def crb_client(crb_app):
    return crb_app.test_client()


@pytest.fixture()
def login_as(crb_client):
    def _login(email):
        r = crb_client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200
        return {"Authorization": f"Bearer {r.get_json()['access_token']}"}
    return _login


@pytest.fixture()
def subscriber_headers(crb_client):
    """Auth headers for the premium 'Demo Bank' subscriber (known key)."""
    raw, prefix, key_hash = auth_service.generate_api_key()
    sub = db.session.query(Subscriber).filter_by(name="Demo Bank").one()
    sub.api_key_prefix, sub.api_key_hash = prefix, key_hash
    db.session.commit()
    r = crb_client.post("/api/auth/subscriber/verify", headers={"X-API-Key": raw})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.get_json()['access_token']}"}


@pytest.fixture()
def profile(crb_client, login_as):
    """consumer@crb.local with a saved profile."""
    headers = login_as("consumer@crb.local")
    r = crb_client.put("/api/consumers/me", headers=headers, json={
        "full_name": "Test Consumer", "national_id": "12345678",
        "phone": "0712345678", "address": "Nairobi",
    })
    assert r.status_code == 201
    return {"id": r.get_json()["id"], "headers": headers}