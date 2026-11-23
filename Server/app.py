from flask import Flask, jsonify
from marshmallow import ValidationError

from config import Config
from extensions import cors, db, jwt, migrate
from controllers.consumer import consumer_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app)

    from models import RevokedToken
    from controllers.auth import auth_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(consumer_bp)
    @jwt.unauthorized_loader
    def _missing(reason):
        return jsonify(error="unauthorized", message=reason), 401

    @jwt.invalid_token_loader
    def _invalid(reason):
        return jsonify(error="unauthorized", message=reason), 401

    @jwt.expired_token_loader
    def _expired(header, payload):
        return jsonify(error="unauthorized", message="Token has expired"), 401

    @jwt.revoked_token_loader
    def _revoked(header, payload):
        return jsonify(error="unauthorized", message="Token has been revoked"), 401

    @jwt.token_in_blocklist_loader
    def _is_revoked(header, payload):
        return db.session.query(RevokedToken.id).filter_by(jti=payload["jti"]).first() is not None

    @app.errorhandler(ValidationError)
    def _validation(err):
        return jsonify(error="validation_error", messages=err.messages), 422

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
