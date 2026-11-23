import copy

FULL_ACCESS_ROLES = {"compliance", "admin"}
MASKED_STAFF_ROLES = {"analyst", "regulator"}


def mask_tail(value, keep=3):
    if not value:
        return value
    return "*" * max(len(value) - keep, 0) + value[-keep:]


def viewer_from_claims(claims, consumer_id):
    """Describe who is looking, relative to the consumer whose data is requested."""
    kind = claims.get("kind")
    role = claims.get("role")
    return {
        "kind": kind,
        "role": role,
        "tier": claims.get("tier"),
        "is_self": kind == "user" and role == "consumer" and claims.get("sub") == str(consumer_id),
    }


def viewer_level(viewer):
    if viewer.get("is_self"):
        return "self"
    if viewer.get("kind") == "subscriber":
        return "subscriber"
    role = viewer.get("role")
    if role in FULL_ACCESS_ROLES:
        return "full"
    if role in MASKED_STAFF_ROLES:
        return "masked"
    raise PermissionError("Viewer has no report visibility")


def filter_report(report, viewer):
    """
    self        everything about me, including soft inquiries
    full        compliance/admin: everything, unmasked
    masked      analyst/regulator: ID/phone masked, no address, all inquiries
    subscriber  ID/phone masked, no address, HARD inquiries only;
                basic tier gets the hard-inquiry count but no list
    """
    level = viewer_level(viewer)
    out = copy.deepcopy(report)

    if level in ("masked", "subscriber"):
        c = out["consumer"]
        c["national_id"] = mask_tail(c.get("national_id"))
        c["phone"] = mask_tail(c.get("phone"))
        c["address"] = None
        c["date_of_birth"] = None

    inquiries = out["inquiries"]
    if level == "subscriber":
        inquiries = [i for i in inquiries if i["type"] == "hard"]
        if viewer.get("tier") == "basic":
            inquiries = []
        out["inquiries"] = inquiries
        out["inquiry_summary"] = {"hard_12m": out["inquiry_summary"]["hard_12m"]}

    return out