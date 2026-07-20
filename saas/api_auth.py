"""Public account and session endpoints."""

from __future__ import annotations

import re

from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy.exc import IntegrityError

from saas.authn import csrf_token, current_session_user, require_csrf, require_user
from saas.billing import grant_credits
from saas.extensions import db
from saas.extensions import limiter
from saas.models import Membership, Organization, User, new_id

auth_api = Blueprint("auth_api", __name__, url_prefix="/api/auth")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _organization_slug(display_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-") or "workspace"
    return f"{base[:140]}-{new_id()[:8]}"


def _session_payload(user: User) -> dict:
    memberships = Membership.query.filter_by(user_id=user.id).all()
    return {
        "status": "success",
        "user": user.to_dict(),
        "organizations": [
            {**membership.organization.to_dict(), "role": membership.role}
            for membership in memberships
        ],
        "csrf_token": csrf_token(),
    }


@auth_api.post("/register")
@limiter.limit("5 per minute")
def register():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    display_name = str(payload.get("display_name", "")).strip()
    password = str(payload.get("password", ""))

    if not EMAIL_RE.fullmatch(email):
        return jsonify({"status": "error", "error": "Enter a valid email address."}), 400
    if len(display_name) < 2 or len(display_name) > 120:
        return jsonify({"status": "error", "error": "Display name must be 2-120 characters."}), 400
    if len(password) < 10:
        return jsonify({"status": "error", "error": "Password must be at least 10 characters."}), 400

    user = User(email=email, display_name=display_name)
    user.set_password(password)
    organization = Organization(name=f"{display_name}'s studio", slug=_organization_slug(display_name))
    membership = Membership(user=user, organization=organization, role="owner")
    db.session.add_all([user, organization, membership])

    try:
        db.session.flush()
        grant_credits(
            organization.id,
            int(current_app.config.get("FREE_CREDITS", 15)),
            event_type="signup_grant",
            idempotency_key=f"signup:{user.id}",
            metadata={"source": "registration"},
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"status": "error", "error": "An account with this email already exists."}), 409

    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    return jsonify(_session_payload(user)), 201


@auth_api.post("/login")
@limiter.limit("10 per minute")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    user = User.query.filter_by(email=email).first()

    if not user or user.status != "active" or not user.check_password(password):
        return jsonify({"status": "error", "error": "Invalid email or password."}), 401

    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    return jsonify(_session_payload(user))


@auth_api.post("/logout")
@require_user
@require_csrf
def logout():
    session.clear()
    return jsonify({"status": "success"})


@auth_api.get("/me")
def me():
    user = current_session_user()
    if not user:
        return jsonify({"status": "anonymous", "user": None})
    return jsonify(_session_payload(user))
