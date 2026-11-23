from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from schemas.auth_schema import LoginSchema, RegisterSchema
from services import auth_service
from services.auth_services import AuthError
from extensions import db

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.app_errorhandler(AuthError)
def _auth_error(err):
    return jsonify(error="auth_error", message=err.message), err.status


def _body():
    return request.get_json(silent=True) or {}


@auth_bp.post("/register")
def register():
    data = RegisterSchema().load(_body())
    user = auth_service.register_consumer(**data)
    return jsonify(user=auth_service.user_public(user), **auth_service.issue_user_tokens(user)), 201


@auth_bp.post("/login")
def login():
    data = LoginSchema().load(_body())
    user = auth_service.authenticate_user(data["email"], data["password"])
    return jsonify(user=auth_service.user_public(user), **auth_service.issue_user_tokens(user))


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    return jsonify(auth_service.refresh_user_token(int(get_jwt_identity())))


@auth_bp.post("/logout")
@jwt_required(verify_type=False)  # accepts access or refresh token
def logout():
    auth_service.revoke_token(get_jwt())
    return jsonify(message="Logged out")


@auth_bp.post("/subscriber/verify")
def subscriber_verify():
    sub = auth_service.authenticate_subscriber(request.headers.get("X-API-Key", ""))
    return jsonify(
        subscriber={"id": sub.id, "name": sub.name, "tier": sub.tier},
        **auth_service.issue_subscriber_token(sub),
    )


@auth_bp.get("/me")
@jwt_required()
def me():
    claims = get_jwt()
    return jsonify(id=claims["sub"], kind=claims["kind"], role=claims["role"])