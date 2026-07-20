"""Session authentication and CSRF helpers for the public SaaS API."""

from __future__ import annotations

import secrets
from functools import wraps

from flask import g, jsonify, request, session

from saas.extensions import db
from saas.models import User


def current_session_user() -> User | None:
    """Return the active session user, caching the lookup for this request."""
    cached = getattr(g, "current_user", None)
    if cached is not None:
        return cached

    user_id = str(session.get("user_id", "")).strip()
    if not user_id:
        return None

    user = db.session.get(User, user_id)
    if not user or user.status != "active":
        session.clear()
        return None

    g.current_user = user
    return user


def csrf_token() -> str:
    token = str(session.get("csrf_token", "")).strip()
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_session_user():
            return jsonify({"status": "error", "error": "Authentication required."}), 401
        return fn(*args, **kwargs)

    return wrapper

def require_csrf(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = str(session.get("csrf_token", ""))
        supplied = str(request.headers.get("X-CSRF-Token", ""))
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            return jsonify({"status": "error", "error": "Invalid CSRF token."}), 403
        return fn(*args, **kwargs)

    return wrapper
