from datetime import date

from services.scoring_engine import SCORE_MAX, SCORE_MIN, calculate_score

AS_OF = date(2026, 11, 23)


def tl(**kw):
    base = dict(status="active", original_amount=100000, outstanding_balance=10000,
                opened_at=date(2020, 1, 1), days_past_due=0, worst_delinquency_days=0,
                account_type="loan")
    return {**base, **kw}


def test_no_history_has_no_score():
    r = calculate_score([])
    assert r["score"] is None and r["band"] == "insufficient_history"


def test_clean_file_scores_high_and_in_range():
    r = calculate_score([tl(), tl(account_type="credit_card"), tl(account_type="telco")], 0, AS_OF)
    assert r["score"] >= 740 and SCORE_MIN <= r["score"] <= SCORE_MAX


def test_default_lowers_score():
    good = calculate_score([tl()], 0, AS_OF)["score"]
    bad = calculate_score([tl(status="defaulted")], 0, AS_OF)["score"]
    assert bad < good


def test_hard_inquiries_lower_score():
    none = calculate_score([tl()], 0, AS_OF)["score"]
    many = calculate_score([tl()], 4, AS_OF)["score"]
    assert many < none


def test_high_utilization_lowers_score():
    low = calculate_score([tl(outstanding_balance=10000)], 0, AS_OF)["score"]
    high = calculate_score([tl(outstanding_balance=100000)], 0, AS_OF)["score"]
    assert high < low
    