from functools import wraps

from flask import g, jsonify, request
from flask_jwt_extended import get_jwt, verify_jwt_in_request

TIER_ORDER = {"basic": 1, "standard": 2, "premium": 3}
PURPOSE_HEADER = "X-Permissible-Purpose"


def _forbidden(message):
    return jsonify(error="forbidden", message=message), 403


def require_roles(*roles):
    """401 if no/invalid token, 403 if the token's role is not allowed."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            if get_jwt().get("role") not in roles:
                return _forbidden("Insufficient role")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_tier(minimum):
    """Subscriber-only: token tier must be >= minimum."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("kind") != "subscriber":
                return _forbidden("Subscriber access only")
            if TIER_ORDER.get(claims.get("tier"), 0) < TIER_ORDER[minimum]:
                return _forbidden(f"Requires {minimum} tier or higher")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_permissible_purpose(*allowed):
    """
    Subscriber must state a purpose in the X-Permissible-Purpose header that is
    (a) in the purposes granted to them and (b) valid for this endpoint.
    The accepted purpose is stored on g.purpose for audit logging.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("kind") != "subscriber":
                return _forbidden("Subscriber access only")
            purpose = request.headers.get(PURPOSE_HEADER)
            if not purpose:
                return _forbidden(f"{PURPOSE_HEADER} header required")
            if purpose not in claims.get("purposes", []):
                return _forbidden("Purpose not granted to this subscriber")
            if allowed and purpose not in allowed:
                return _forbidden("Purpose not permitted for this endpoint")
            g.purpose = purpose
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_self_or_roles(param, *roles):
    """Consumers may only touch their own resource (URL param == token identity).
    Roles listed in `roles` (e.g. analyst, admin) bypass the ownership check."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("role") in roles:
                return fn(*args, **kwargs)
            if claims.get("kind") == "user" and str(kwargs.get(param)) == claims["sub"]:
                return fn(*args, **kwargs)
            return _forbidden("You can only access your own data")
        return wrapper
    return decorator