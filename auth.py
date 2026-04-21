"""HTTP Basic Auth decorator."""

import os
from functools import wraps

from flask import Response, request


def _unauthorized() -> Response:
    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'},
    )


def require_basic_auth(fn):
    """Simple HTTP Basic Auth protection for Flask routes."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        username = os.getenv("BASIC_AUTH_USERNAME")
        password = os.getenv("BASIC_AUTH_PASSWORD")

        if not auth or auth.username != username or auth.password != password:
            return _unauthorized()

        return fn(*args, **kwargs)

    return wrapper
