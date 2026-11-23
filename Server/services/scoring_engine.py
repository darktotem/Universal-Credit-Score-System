from datetime import date, datetime

SCORE_MIN, SCORE_MAX = 300, 850

WEIGHTS = {
    "payment_history": 0.35,
    "utilization": 0.30,
    "history_length": 0.15,
    "account_mix": 0.10,
    "inquiries": 0.10,
}

BANDS = [(740, "excellent"), (670, "good"), (580, "fair"), (500, "poor"), (0, "very_poor")]


def _to_date(value):
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def _band(score):
    return next(name for floor, name in BANDS if score >= floor)


def _payment_value(t):
    if (t.get("status") or "").lower() in ("defaulted", "written_off"):
        return 0.0
    dpd = max(t.get("worst_delinquency_days") or 0, t.get("days_past_due") or 0)
    if dpd == 0:
        return 1.0
    if dpd < 30:
        return 0.8
    if dpd < 60:
        return 0.5
    if dpd < 90:
        return 0.25
    return 0.0


def _utilization_value(tradelines):
    active = [t for t in tradelines if (t.get("status") or "").lower() == "active"
              and (t.get("original_amount") or 0) > 0]
    if not active:
        return 1.0
    ratio = (sum(t.get("outstanding_balance") or 0 for t in active)
             / sum(t["original_amount"] for t in active))
    if ratio <= 0.3:
        return 1.0
    return max(0.0, 1.0 - (ratio - 0.3) / 0.7)


def calculate_score(tradelines, hard_inquiries_12m=0, as_of=None):
    """
    tradelines: list of plain dicts with keys status, original_amount, outstanding_balance,
    opened_at, days_past_due, worst_delinquency_days, account_type.
    Returns {"score", "band", "factors"}; score is None when there is no history.
    """
    if not tradelines:
        return {"score": None, "band": "insufficient_history", "factors": {}}

    as_of = _to_date(as_of) or date.today()

    payment = sum(_payment_value(t) for t in tradelines) / len(tradelines)
    utilization = _utilization_value(tradelines)

    opened = [d for d in (_to_date(t.get("opened_at")) for t in tradelines) if d]
    months = (as_of - min(opened)).days / 30.4 if opened else 0
    history = min(max(months, 0) / 60, 1.0)

    mix = min(len({t.get("account_type") for t in tradelines if t.get("account_type")}) / 3, 1.0)
    inquiries = max(0.0, 1.0 - 0.25 * hard_inquiries_12m)

    values = {
        "payment_history": payment,
        "utilization": utilization,
        "history_length": history,
        "account_mix": mix,
        "inquiries": inquiries,
    }
    weighted = sum(WEIGHTS[k] * v for k, v in values.items())
    score = SCORE_MIN + round((SCORE_MAX - SCORE_MIN) * weighted)

    return {
        "score": score,
        "band": _band(score),
        "factors": {
            k: {"weight": WEIGHTS[k], "value": round(v, 3), "contribution": round(WEIGHTS[k] * v, 3)}
            for k, v in values.items()
        },
    }