from datetime import date, timedelta

from extensions import db
from models import Subscriber
from models.audit_log import AuditLog
from models.inquiry import Inquiry
from models.tradeline import Tradeline
from services import auth_service

INGEST = "/api/subscriber/tradelines"
PULL = "/api/subscriber/reports/pull"
CLEAR = "/api/subscriber/clearance"
TODAY = date.today().isoformat()


def sub_headers(client, name):
    """(auth headers, subscriber id) for a seeded subscriber, using a freshly known API key."""
    raw, prefix, key_hash = auth_service.generate_api_key()
    sub = db.session.query(Subscriber).filter_by(name=name).one()
    sub.api_key_prefix, sub.api_key_hash = prefix, key_hash
    db.session.commit()
    r = client.post("/api/auth/subscriber/verify", headers={"X-API-Key": raw})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.get_json()['access_token']}"}, sub.id


def tl(**kw):
    base = dict(external_ref="ACC-001", national_id="12345678", account_type="personal_loan",
                status="active", original_amount="100000.00", outstanding_balance="40000.00",
                opened_at="2024-01-15", days_past_due=0, reported_at=TODAY)
    return {**base, **kw}


def ingest(client, headers, *records):
    return client.post(INGEST, headers=headers, json={"tradelines": list(records)})


def grant(client, profile, sub_id, purpose):
    r = client.post(f"/api/consumers/{profile['id']}/consents", headers=profile["headers"],
                    json={"subscriber_id": sub_id, "purpose": purpose})
    assert r.status_code == 201
    return r.get_json()["id"]


def purpose(p, headers):
    return {**headers, "X-Permissible-Purpose": p}


# ---------------- ingestion ----------------
def test_ingest_requires_subscriber_token(crb_client, profile):
    assert crb_client.post(INGEST, json={"tradelines": [tl()]}).status_code == 401
    assert crb_client.post(INGEST, headers=profile["headers"], json={"tradelines": [tl()]}).status_code == 403


def test_ingest_creates_and_links_known_consumer(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    r = ingest(crb_client, bank, tl())
    assert r.status_code == 200
    body = r.get_json()
    assert (body["created"], body["updated"], body["pending_link"]) == (1, 0, 0)
    assert db.session.query(Tradeline).one().consumer_id == profile["id"]


def test_unknown_national_id_is_pending_link(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    body = ingest(crb_client, bank, tl(national_id="99999999")).get_json()
    assert body["created"] == 1 and body["pending_link"] == 1


def test_upsert_is_idempotent(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    ingest(crb_client, bank, tl())
    body = ingest(crb_client, bank, tl()).get_json()
    assert (body["created"], body["updated"]) == (0, 1)
    assert db.session.query(Tradeline).count() == 1


def test_upsert_updates_fields(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    ingest(crb_client, bank, tl())
    ingest(crb_client, bank, tl(outstanding_balance="10000.00", days_past_due=35))
    db.session.expire_all()
    row = db.session.query(Tradeline).one()
    assert row.outstanding_balance == 10000.0
    assert row.days_past_due == 35 and row.worst_delinquency_days == 35


def test_stale_report_rejected(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    ingest(crb_client, bank, tl())
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = ingest(crb_client, bank, tl(reported_at=yesterday))
    assert r.status_code == 422
    assert "reported_at" in r.get_json()["rejected"][0]["errors"]


def test_account_cannot_change_owner(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    ingest(crb_client, bank, tl())
    r = ingest(crb_client, bank, tl(national_id="87654321"))
    assert r.status_code == 422
    assert "national_id" in r.get_json()["rejected"][0]["errors"]


def test_partial_batch_saves_valid_rows(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = ingest(
        crb_client, bank,
        tl(external_ref="A1"),
        tl(external_ref="A2", original_amount="-5"),
        tl(external_ref="A3", status="paused"),
        tl(external_ref="A4", opened_at=tomorrow),
    )
    body = r.get_json()
    assert r.status_code == 200 and body["created"] == 1
    assert [x["index"] for x in body["rejected"]] == [1, 2, 3]


def test_all_invalid_batch_is_422(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    assert ingest(crb_client, bank, tl(national_id="1")).status_code == 422


def test_batch_size_limits(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    assert crb_client.post(INGEST, headers=bank, json={"tradelines": []}).status_code == 422
    many = [tl(external_ref=f"R{i}") for i in range(501)]
    assert crb_client.post(INGEST, headers=bank, json={"tradelines": many}).status_code == 422


def test_duplicate_ref_within_batch_rejected(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    body = ingest(crb_client, bank, tl(), tl()).get_json()
    assert body["created"] == 1 and len(body["rejected"]) == 1


def test_closed_account_must_have_zero_balance_and_close_date(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    r = ingest(crb_client, bank, tl(status="closed"))
    errors = r.get_json()["rejected"][0]["errors"]
    assert "outstanding_balance" in errors and "closed_at" in errors
    ok = ingest(crb_client, bank, tl(status="closed", outstanding_balance="0", closed_at="2025-06-01"))
    assert ok.status_code == 200


def test_ingest_is_audited(crb_client, profile):
    bank, bank_id = sub_headers(crb_client, "Demo Bank")
    ingest(crb_client, bank, tl())
    row = db.session.query(AuditLog).filter_by(action="tradeline.ingest").one()
    assert row.actor_kind == "subscriber"
    assert row.details["created"] == 1 and row.details["subscriber_id"] == bank_id


def test_pending_tradeline_links_when_consumer_registers(crb_client):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    ingest(crb_client, bank, tl(national_id="99999999"))
    r = crb_client.post("/api/auth/register", json={
        "email": "late@x.com", "password": "longenough1", "full_name": "Late Joiner"})
    headers = {"Authorization": f"Bearer {r.get_json()['access_token']}"}
    user_id = r.get_json()["user"]["id"]
    crb_client.put("/api/consumers/me", headers=headers,
                   json={"full_name": "Late Joiner", "national_id": "999 999-99"})
    db.session.expire_all()
    assert db.session.query(Tradeline).one().consumer_id == user_id


# ---------------- report pull ----------------
def test_pull_needs_consent_then_succeeds(crb_client, profile):
    bank, bank_id = sub_headers(crb_client, "Demo Bank")
    ingest(crb_client, bank, tl())
    headers = purpose("credit_application", bank)

    r = crb_client.post(PULL, headers=headers, json={"national_id": "12345678"})
    assert r.status_code == 404
    assert db.session.query(AuditLog).filter_by(action="report.pull_denied").count() == 1

    grant(crb_client, profile, bank_id, "credit_application")
    r = crb_client.post(PULL, headers=headers, json={"national_id": "12345678"})
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["tradelines"]) == 1
    assert body["consumer"]["national_id"].startswith("*")  # subscribers see masked IDs
    assert body["score"]["score"] is not None

    inquiry = db.session.query(Inquiry).filter_by(subscriber_id=bank_id).one()
    assert inquiry.inquiry_type == "hard" and inquiry.consumer_id == profile["id"]
    assert db.session.query(AuditLog).filter_by(action="report.pull").count() == 1


def test_unknown_id_looks_the_same_as_no_consent(crb_client, profile):
    bank, bank_id = sub_headers(crb_client, "Demo Bank")
    headers = purpose("credit_application", bank)
    unknown = crb_client.post(PULL, headers=headers, json={"national_id": "55555555"})
    no_consent = crb_client.post(PULL, headers=headers, json={"national_id": "12345678"})
    assert unknown.status_code == no_consent.status_code == 404
    assert unknown.get_json() == no_consent.get_json()


def test_pull_purpose_header_rules(crb_client, profile):
    sacco, sacco_id = sub_headers(crb_client, "Demo SACCO")  # standard tier, credit_application only
    body = {"national_id": "12345678"}
    assert crb_client.post(PULL, headers=sacco, json=body).status_code == 403  # header missing
    assert crb_client.post(PULL, headers=purpose("collections", sacco), json=body).status_code == 403
    assert crb_client.post(PULL, headers=purpose("marketing", sacco), json=body).status_code == 403


def test_basic_tier_cannot_pull_full_report(crb_client, profile):
    telco, _ = sub_headers(crb_client, "Demo Telco")
    r = crb_client.post(PULL, headers=purpose("credit_application", telco),
                        json={"national_id": "12345678"})
    assert r.status_code == 403


def test_non_subscriber_tokens_cannot_pull(crb_client, profile):
    assert crb_client.post(PULL, json={"national_id": "12345678"}).status_code == 401
    assert crb_client.post(PULL, headers=purpose("credit_application", profile["headers"]),
                           json={"national_id": "12345678"}).status_code == 403


def test_account_review_pull_is_a_soft_inquiry(crb_client, profile):
    bank, bank_id = sub_headers(crb_client, "Demo Bank")
    grant(crb_client, profile, bank_id, "account_review")
    r = crb_client.post(PULL, headers=purpose("account_review", bank), json={"national_id": "12345678"})
    assert r.status_code == 200
    assert db.session.query(Inquiry).filter_by(subscriber_id=bank_id).one().inquiry_type == "soft"


def test_revoked_consent_blocks_pull(crb_client, profile):
    bank, bank_id = sub_headers(crb_client, "Demo Bank")
    consent_id = grant(crb_client, profile, bank_id, "credit_application")
    crb_client.delete(f"/api/consumers/{profile['id']}/consents/{consent_id}", headers=profile["headers"])
    r = crb_client.post(PULL, headers=purpose("credit_application", bank),
                        json={"national_id": "12345678"})
    assert r.status_code == 404


# ---------------- clearance ----------------
def test_clearance_flags_default_and_works_for_basic_tier(crb_client, profile):
    bank, _ = sub_headers(crb_client, "Demo Bank")
    telco, telco_id = sub_headers(crb_client, "Demo Telco")
    ingest(crb_client, bank, tl(status="defaulted", days_past_due=120))
    grant(crb_client, profile, telco_id, "credit_application")

    r = crb_client.post(CLEAR, headers=purpose("credit_application", telco),
                        json={"national_id": "12345678"})
    body = r.get_json()
    assert r.status_code == 200
    assert body["result"] == "adverse" and "defaulted_account" in body["flags"]
    assert "score" not in body  # clearance never exposes the numeric score


def test_clearance_clear_and_no_history(crb_client, profile):
    bank, bank_id = sub_headers(crb_client, "Demo Bank")
    grant(crb_client, profile, bank_id, "credit_application")
    headers = purpose("credit_application", bank)
    body = {"national_id": "12345678"}
    assert crb_client.post(CLEAR, headers=headers, json=body).get_json()["result"] == "no_history"
    ingest(crb_client, bank, tl())
    assert crb_client.post(CLEAR, headers=headers, json=body).get_json()["result"] == "clear"