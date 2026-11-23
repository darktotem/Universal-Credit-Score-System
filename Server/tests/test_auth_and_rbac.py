import pytest
from flask import Blueprint, jsonify

from models import Subscriber
from services import auth_service
from utils.rbac import (
    require_permissible_purpose, require_roles, require_self_or_roles, require_tier,
)
from config import TestConfig
from extensions import db
from seed import seed

PASSWORD = "ChangeMe123!"


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    probe = Blueprint("probe", __name__, url_prefix="/probe")

    @probe.get("/admin")
    @require_roles("admin")
    def admin_only():
        return jsonify(ok=True)

    @probe.get("/premium")
    @require_tier("premium")
    def premium_only():
        return jsonify(ok=True)

    @probe.get("/purpose")
    @require_permissible_purpose("credit_application")
    def purpose_only():
        return jsonify(ok=True)

    @probe.get("/consumers/<int:consumer_id>")
    @require_self_or_roles("consumer_id", "admin", "analyst")
    def consumer_data(consumer_id):
        return jsonify(ok=True)

    app.register_blueprint(probe)

    with app.app_context():
        db.create_all()
        seed()
        # known key for the basic-tier subscriber
        raw, prefix, key_hash = auth_service.generate_api_key()
        sub = db.session.query(Subscriber).filter_by(name="Demo Telco").one()
        sub.api_key_prefix, sub.api_key_hash = prefix, key_hash
        db.session.commit()
        app.config["TELCO_KEY"] = raw
        raw, prefix, key_hash = auth_service.generate_api_key()
        sub = db.session.query(Subscriber).filter_by(name="Demo Bank").one()
        sub.api_key_prefix, sub.api_key_hash = prefix, key_hash
        db.session.commit()
        app.config["BANK_KEY"] = raw
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    return r.get_json()


def bearer(token, **extra):
    return {"Authorization": f"Bearer {token}", **extra}


def sub_token(client, key):
    r = client.post("/api/auth/subscriber/verify", headers={"X-API-Key": key})
    assert r.status_code == 200
    return r.get_json()["access_token"]


# ---- authentication: 401 ----
def test_login_wrong_password_401(client):
    r = client.post("/api/auth/login", json={"email": "admin@crb.local", "password": "nope"})
    assert r.status_code == 401


def test_missing_token_401(client):
    assert client.get("/probe/admin").status_code == 401


def test_garbage_token_401(client):
    assert client.get("/probe/admin", headers=bearer("not.a.jwt")).status_code == 401


def test_bad_api_key_401(client):
    r = client.post("/api/auth/subscriber/verify", headers={"X-API-Key": "crb_deadbeef_wrong"})
    assert r.status_code == 401


def test_logout_revokes_token_401(client):
    token = login(client, "admin@crb.local")["access_token"]
    assert client.get("/probe/admin", headers=bearer(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=bearer(token)).status_code == 200
    assert client.get("/probe/admin", headers=bearer(token)).status_code == 401


def test_register_always_creates_consumer(client):
    r = client.post("/api/auth/register", json={
        "email": "new@x.com", "password": "longenough1", "full_name": "New", "role": "admin",
    })
    assert r.status_code in (201, 422)  # extra "role" field is rejected or ignored
    if r.status_code == 201:
        assert r.get_json()["user"]["role"] == "consumer"


# ---- authorization: 403 ----
def test_consumer_cannot_hit_admin_403(client):
    token = login(client, "consumer@crb.local")["access_token"]
    assert client.get("/probe/admin", headers=bearer(token)).status_code == 403


def test_admin_can_hit_admin(client):
    token = login(client, "admin@crb.local")["access_token"]
    assert client.get("/probe/admin", headers=bearer(token)).status_code == 200


def test_user_token_cannot_use_subscriber_tier_route(client):
    token = login(client, "admin@crb.local")["access_token"]
    assert client.get("/probe/premium", headers=bearer(token)).status_code == 403


def test_basic_tier_blocked_premium_allowed(client, app):
    basic = sub_token(client, app.config["TELCO_KEY"])
    premium = sub_token(client, app.config["BANK_KEY"])
    assert client.get("/probe/premium", headers=bearer(basic)).status_code == 403
    assert client.get("/probe/premium", headers=bearer(premium)).status_code == 200


def test_purpose_header_required_and_checked(client, app):
    token = sub_token(client, app.config["BANK_KEY"])
    assert client.get("/probe/purpose", headers=bearer(token)).status_code == 403
    bad = bearer(token, **{"X-Permissible-Purpose": "marketing"})
    assert client.get("/probe/purpose", headers=bad).status_code == 403
    good = bearer(token, **{"X-Permissible-Purpose": "credit_application"})
    assert client.get("/probe/purpose", headers=good).status_code == 200


def test_ownership_check(client):
    data = login(client, "consumer@crb.local")
    me_id = int(client.get("/api/auth/me", headers=bearer(data["access_token"])).get_json()["id"])
    assert client.get(f"/probe/consumers/{me_id}", headers=bearer(data["access_token"])).status_code == 200
    assert client.get(f"/probe/consumers/{me_id + 999}", headers=bearer(data["access_token"])).status_code == 403
    analyst = login(client, "analyst@crb.local")["access_token"]
    assert client.get(f"/probe/consumers/{me_id}", headers=bearer(analyst)).status_code == 200