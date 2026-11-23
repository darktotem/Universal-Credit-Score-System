from extensions import db
from models import Subscriber
from models.inquiry import Inquiry
from services.report_builder import build_report
from models.consumer import Consumer
from utils.masking import filter_report


def report_url(consumer_id):
    return f"/api/consumers/{consumer_id}/report"


# ---- who may call the endpoint ----
def test_no_token_401(crb_client, profile):
    assert crb_client.get(report_url(profile["id"])).status_code == 401


def test_other_consumer_403(crb_client, profile):
    r = crb_client.post("/api/auth/register", json={
        "email": "other@x.com", "password": "longenough1", "full_name": "Other"})
    other = {"Authorization": f"Bearer {r.get_json()['access_token']}"}
    assert crb_client.get(report_url(profile["id"]), headers=other).status_code == 403


def test_subscriber_token_cannot_use_consumer_routes_403(crb_client, profile, subscriber_headers):
    assert crb_client.get(report_url(profile["id"]), headers=subscriber_headers).status_code == 403


def test_unknown_consumer_404(crb_client, login_as):
    assert crb_client.get(report_url(9999), headers=login_as("admin@crb.local")).status_code == 404


# ---- what each role sees ----
def test_consumer_sees_own_full_report(crb_client, profile):
    body = crb_client.get(report_url(profile["id"]), headers=profile["headers"]).get_json()
    assert body["consumer"]["national_id"] == "12345678"
    assert body["consumer"]["address"] == "Nairobi"


def test_analyst_sees_masked_data(crb_client, profile, login_as):
    body = crb_client.get(report_url(profile["id"]), headers=login_as("analyst@crb.local")).get_json()
    nid = body["consumer"]["national_id"]
    assert nid.startswith("*") and nid.endswith("678")
    assert body["consumer"]["address"] is None


def test_regulator_sees_masked_data(crb_client, profile, login_as):
    body = crb_client.get(report_url(profile["id"]), headers=login_as("regulator@crb.local")).get_json()
    assert body["consumer"]["national_id"].startswith("*")


def test_admin_and_compliance_see_unmasked(crb_client, profile, login_as):
    for email in ("admin@crb.local", "compliance@crb.local"):
        body = crb_client.get(report_url(profile["id"]), headers=login_as(email)).get_json()
        assert body["consumer"]["national_id"] == "12345678"


# ---- inquiry visibility ----
def _seed_inquiries(consumer_id):
    bank = db.session.query(Subscriber).filter_by(name="Demo Bank").one()
    telco = db.session.query(Subscriber).filter_by(name="Demo Telco").one()
    db.session.add_all([
        Inquiry(consumer_id=consumer_id, subscriber_id=bank.id, purpose="credit_application", inquiry_type="hard"),
        Inquiry(consumer_id=consumer_id, subscriber_id=telco.id, purpose="account_review", inquiry_type="soft"),
        Inquiry(consumer_id=consumer_id, subscriber_id=None, purpose="self_check", inquiry_type="soft"),
    ])
    db.session.commit()


def test_soft_inquiries_hidden_from_subscribers(crb_app, profile):
    _seed_inquiries(profile["id"])
    consumer = db.session.get(Consumer, profile["id"])

    def viewer(**kw):
        return {"kind": "subscriber", "role": "subscriber", "tier": "standard",
                "is_self": False, **kw}

    raw = build_report(consumer, {"kind": "user", "role": "admin", "is_self": False})
    assert len(raw["inquiries"]) == 3

    standard = build_report(consumer, viewer())
    assert {i["type"] for i in standard["inquiries"]} == {"hard"}
    assert "soft_12m" not in standard["inquiry_summary"]

    basic = build_report(consumer, viewer(tier="basic"))
    assert basic["inquiries"] == []
    assert basic["inquiry_summary"] == {"hard_12m": 1}


def test_consumer_sees_own_soft_inquiries(crb_app, profile):
    _seed_inquiries(profile["id"])
    consumer = db.session.get(Consumer, profile["id"])
    own = build_report(consumer, {"kind": "user", "role": "consumer", "is_self": True})
    assert len(own["inquiries"]) == 3


def test_self_report_view_creates_soft_inquiry(crb_client, profile):
    crb_client.get(report_url(profile["id"]), headers=profile["headers"])
    body = crb_client.get(report_url(profile["id"]), headers=profile["headers"]).get_json()
    assert any(i["purpose"] == "self_check" and i["type"] == "soft" for i in body["inquiries"])


def test_staff_view_does_not_create_inquiry(crb_client, profile, login_as):
    crb_client.get(report_url(profile["id"]), headers=login_as("analyst@crb.local"))
    assert db.session.query(Inquiry).count() == 0


def test_filter_report_rejects_unknown_viewer():
    import pytest
    with pytest.raises(PermissionError):
        filter_report({"consumer": {}, "inquiries": [], "inquiry_summary": {}},
                      {"kind": "user", "role": "nobody", "is_self": False})