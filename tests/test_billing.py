"""Credit ledger and signed Lemon Squeezy webhook tests."""

from __future__ import annotations

import hashlib
import hmac
import json

from app import create_app


def _app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "AUTO_CREATE_DB": True,
            "STORAGE_LOCAL_ROOT": str(tmp_path / "storage"),
            "LEMONSQUEEZY_WEBHOOK_SECRET": "webhook-test-secret",
            "LEMONSQUEEZY_CREATOR_VARIANT_ID": "101",
        }
    )


def _register(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "billing@example.com",
            "display_name": "Billing Creator",
            "password": "long-test-password",
        },
    )
    assert response.status_code == 201
    return response.get_json()


def _signed_webhook(client, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"webhook-test-secret", body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/billing/webhooks/lemonsqueezy",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )


def test_registration_grants_free_credits(tmp_path) -> None:
    client = _app(tmp_path).test_client()
    registered = _register(client)
    organization_id = registered["organizations"][0]["id"]

    response = client.get(f"/api/billing?organization_id={organization_id}")

    assert response.status_code == 200
    assert response.get_json()["credit_balance"] == 15


def test_subscription_payment_grants_plan_credits_once(tmp_path) -> None:
    client = _app(tmp_path).test_client()
    registered = _register(client)
    organization_id = registered["organizations"][0]["id"]
    subscription = {
        "meta": {
            "event_name": "subscription_created",
            "custom_data": {"organization_id": organization_id},
        },
        "data": {
            "type": "subscriptions",
            "id": "sub_42",
            "attributes": {
                "customer_id": 9,
                "variant_id": 101,
                "status": "active",
                "renews_at": "2026-08-20T00:00:00Z",
                "ends_at": None,
            },
        },
    }
    assert _signed_webhook(client, subscription).status_code == 200

    payment = {
        "meta": {"event_name": "subscription_payment_success"},
        "data": {
            "type": "subscription-invoices",
            "id": "invoice_42",
            "attributes": {"subscription_id": "sub_42"},
        },
    }
    first = _signed_webhook(client, payment)
    duplicate = _signed_webhook(client, payment)

    assert first.status_code == 200
    assert duplicate.get_json()["duplicate"] is True
    overview = client.get(f"/api/billing?organization_id={organization_id}").get_json()
    assert overview["credit_balance"] == 315
    assert overview["subscription"]["plan_key"] == "creator"


def test_webhook_rejects_invalid_signature(tmp_path) -> None:
    client = _app(tmp_path).test_client()
    response = client.post(
        "/api/billing/webhooks/lemonsqueezy",
        json={"meta": {"event_name": "subscription_updated"}},
        headers={"X-Signature": "wrong"},
    )

    assert response.status_code == 401
