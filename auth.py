"""HTTP Basic Auth decorator for Flask routes."""

import os
import secrets
from functools import wraps

from flask import Response, current_app, request
from dotenv import load_dotenv

load_dotenv()


def _expected_credentials() -> tuple[str, str]:
    is_production = str(current_app.config.get("ENV", "development")).lower() == "production"
    username = os.getenv("APP_USERNAME", "" if is_production else "admin")
    password = os.getenv("APP_PASSWORD", "" if is_production else "changeme")
    return username, password

def require_auth(fn):
    """Protect a Flask route with HTTP Basic Authentication."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Public SaaS sessions and legacy Basic Auth coexist during migration.
        from saas.authn import current_session_user  # pylint: disable=import-outside-toplevel

        if current_session_user():
            return fn(*args, **kwargs)

        if not current_app.config.get("ALLOW_BASIC_AUTH", True):
            return _unauthorized()

        auth = request.authorization
        username, password = _expected_credentials()

        if not auth:
            return _unauthorized()

        if not username or not password:
            return _unauthorized()

        username_matches = secrets.compare_digest(str(auth.username or ""), username)
        password_matches = secrets.compare_digest(str(auth.password or ""), password)
        if not username_matches or not password_matches:
            return _unauthorized()

        return fn(*args, **kwargs)

    return wrapper


# Backward-compatible alias for existing imports in early scaffolding.
require_basic_auth = require_auth


def _unauthorized() -> Response:
    return Response(
        "Access denied. Please provide valid credentials.",
        401,
        {"WWW-Authenticate": 'Basic realm="Audiobook Pipeline"'},
    )
