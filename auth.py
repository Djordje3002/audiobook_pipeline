"""HTTP Basic Auth decorator for Flask routes."""

import os
from functools import wraps

from flask import Response, request

USERNAME = os.getenv("APP_USERNAME", "admin")
PASSWORD = os.getenv("APP_PASSWORD", "changeme")

def require_auth(fn):
    """Protect a Flask route with HTTP Basic Authentication."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.authorization

        if not auth:
            return _unauthorized()

        if auth.username != USERNAME or auth.password != PASSWORD:
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
