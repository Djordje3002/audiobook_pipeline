"""Authenticated billing APIs and Lemon Squeezy webhook receiver."""

from __future__ import annotations

import hashlib
import hmac

import requests
from flask import Blueprint, current_app, jsonify, request

from saas.authn import current_session_user, require_csrf, require_user
from saas.billing import (
    ACTIVE_SUBSCRIPTION_STATUSES,
    PLAN_CREDITS,
    LemonSqueezyClient,
    apply_payment_event,
    credit_balance,
    sync_subscription_event,
)
from saas.extensions import db
from saas.models import BillingWebhook, Membership, Subscription, utc_now

billing_api = Blueprint("billing_api", __name__, url_prefix="/api/billing")
SUBSCRIPTION_EVENTS = {
    "subscription_created",
    "subscription_updated",
    "subscription_cancelled",
    "subscription_resumed",
    "subscription_expired",
    "subscription_paused",
    "subscription_unpaused",
}


def _organization_for_user(organization_id: str):
    user = current_session_user()
    membership = Membership.query.filter_by(
        user_id=user.id,
        organization_id=organization_id,
    ).first()
    return membership.organization if membership else None


def _active_subscription(organization_id: str) -> Subscription | None:
    return (
        Subscription.query.filter(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES),
        )
        .order_by(Subscription.updated_at.desc())
        .first()
    )


@billing_api.get("")
@require_user
def overview():
    organization_id = str(request.args.get("organization_id", "")).strip()
    organization = _organization_for_user(organization_id)
    if not organization:
        return jsonify({"status": "error", "error": "Organization not found."}), 404
    subscription = _active_subscription(organization.id)
    return jsonify(
        {
            "status": "success",
            "credit_balance": credit_balance(organization.id),
            "subscription": subscription.to_dict() if subscription else None,
            "plans": [
                {"key": "creator", "credits": PLAN_CREDITS["creator"], "price_usd": 29},
                {"key": "studio", "credits": PLAN_CREDITS["studio"], "price_usd": 79},
            ],
            "checkout_configured": bool(current_app.config.get("LEMONSQUEEZY_API_KEY")),
        }
    )


@billing_api.post("/checkout")
@require_user
@require_csrf
def create_checkout():
    payload = request.get_json(silent=True) or {}
    organization_id = str(payload.get("organization_id", "")).strip()
    plan_key = str(payload.get("plan_key", "")).strip().lower()
    organization = _organization_for_user(organization_id)
    if not organization:
        return jsonify({"status": "error", "error": "Organization not found."}), 404
    if plan_key not in PLAN_CREDITS:
        return jsonify({"status": "error", "error": "Unknown subscription plan."}), 400
    if _active_subscription(organization.id):
        return jsonify({"status": "error", "error": "Manage the existing subscription instead."}), 409
    try:
        url = LemonSqueezyClient().create_checkout(
            organization=organization,
            user=current_session_user(),
            plan_key=plan_key,
        )
    except (RuntimeError, requests.RequestException, KeyError, ValueError) as exc:
        return jsonify({"status": "error", "error": str(exc)}), 503
    return jsonify({"status": "success", "checkout_url": url})


@billing_api.post("/portal")
@require_user
@require_csrf
def customer_portal():
    organization_id = str((request.get_json(silent=True) or {}).get("organization_id", "")).strip()
    organization = _organization_for_user(organization_id)
    if not organization:
        return jsonify({"status": "error", "error": "Organization not found."}), 404
    subscription = _active_subscription(organization.id)
    if not subscription:
        return jsonify({"status": "error", "error": "No active subscription was found."}), 404
    try:
        url = LemonSqueezyClient().customer_portal_url(subscription)
    except (RuntimeError, requests.RequestException, KeyError, ValueError) as exc:
        return jsonify({"status": "error", "error": str(exc)}), 503
    return jsonify({"status": "success", "portal_url": url})


@billing_api.post("/webhooks/lemonsqueezy")
def lemonsqueezy_webhook():
    secret = str(current_app.config.get("LEMONSQUEEZY_WEBHOOK_SECRET", "")).strip()
    if not secret:
        return jsonify({"status": "error", "error": "Webhook receiver is not configured."}), 503
    raw_body = request.get_data(cache=True)
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    supplied = str(request.headers.get("X-Signature", ""))
    if not hmac.compare_digest(expected, supplied):
        return jsonify({"status": "error", "error": "Invalid webhook signature."}), 401

    payload = request.get_json(silent=True) or {}
    event_name = str((payload.get("meta") or {}).get("event_name") or request.headers.get("X-Event-Name", ""))
    data = payload.get("data") or {}
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    record = BillingWebhook.query.filter_by(payload_hash=payload_hash).first()
    if record and record.status == "processed":
        return jsonify({"status": "success", "duplicate": True})
    if not record:
        record = BillingWebhook(
            event_name=event_name,
            provider_object_id=str(data.get("id") or "") or None,
            payload_hash=payload_hash,
            event_payload=payload,
        )
        db.session.add(record)

    try:
        if event_name in SUBSCRIPTION_EVENTS:
            sync_subscription_event(payload)
        elif event_name == "subscription_payment_success":
            apply_payment_event(payload)
        record.status = "processed"
        record.error = None
        record.processed_at = utc_now()
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        record = BillingWebhook.query.filter_by(payload_hash=payload_hash).first() or record
        record.status = "error"
        record.error = str(exc)[:1000]
        db.session.add(record)
        db.session.commit()
        return jsonify({"status": "error", "error": "Webhook processing failed."}), 500
    return jsonify({"status": "success"})
