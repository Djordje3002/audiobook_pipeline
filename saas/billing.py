"""Credit ledger and Lemon Squeezy billing primitives."""

from __future__ import annotations

import math
from datetime import datetime

import requests
from flask import current_app
from sqlalchemy import func

from config import PREVIEW_MINUTES
from saas.extensions import db
from saas.models import Organization, PipelineJob, Project, Subscription, UsageEvent

PLAN_CREDITS = {"creator": 300, "studio": 1200}
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "on_trial", "paused", "past_due"}


class InsufficientCreditsError(RuntimeError):
    def __init__(self, required: int, available: int):
        super().__init__(f"This job needs {required} credits; {available} are available.")
        self.required = required
        self.available = available


def credit_balance(organization_id: str) -> int:
    value = (
        db.session.query(func.coalesce(func.sum(UsageEvent.credits), 0))
        .filter(UsageEvent.organization_id == organization_id)
        .scalar()
    )
    return int(value or 0)


def job_credit_cost(project: Project, mode: str) -> int:
    if not project.duration_seconds or project.duration_seconds <= 0:
        raise ValueError("Source duration is unavailable. Upload a valid audio or video file again.")
    duration_seconds = float(project.duration_seconds)
    if mode == "preview":
        duration_seconds = min(duration_seconds, PREVIEW_MINUTES * 60)
    minutes = max(1, math.ceil(duration_seconds / 60.0))
    return minutes * max(1, len(project.target_languages or []))


def grant_credits(
    organization_id: str,
    credits: int,
    *,
    event_type: str,
    idempotency_key: str,
    metadata: dict | None = None,
) -> UsageEvent:
    existing = UsageEvent.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    event = UsageEvent(
        organization_id=organization_id,
        event_type=event_type,
        credits=abs(int(credits)),
        idempotency_key=idempotency_key,
        event_metadata=metadata or {},
    )
    db.session.add(event)
    return event


def reserve_job_credits(job: PipelineJob) -> int:
    project = job.project
    required = job_credit_cost(project, job.mode)
    db.session.query(Organization).filter_by(id=project.organization_id).with_for_update().one()
    available = credit_balance(project.organization_id)
    if available < required:
        raise InsufficientCreditsError(required, available)
    db.session.add(
        UsageEvent(
            organization_id=project.organization_id,
            project_id=project.id,
            job_id=job.id,
            event_type="job_usage",
            credits=-required,
            idempotency_key=f"job:{job.id}:usage",
            event_metadata={
                "mode": job.mode,
                "duration_seconds": project.duration_seconds,
                "target_languages": list(project.target_languages or []),
            },
        )
    )
    return required


def release_job_credits(job: PipelineJob, reason: str) -> None:
    release_key = f"job:{job.id}:release"
    if UsageEvent.query.filter_by(idempotency_key=release_key).first():
        return
    reservation = UsageEvent.query.filter_by(idempotency_key=f"job:{job.id}:usage").first()
    if not reservation or reservation.credits >= 0:
        return
    db.session.add(
        UsageEvent(
            organization_id=job.project.organization_id,
            project_id=job.project_id,
            job_id=job.id,
            event_type="job_release",
            credits=abs(reservation.credits),
            idempotency_key=release_key,
            event_metadata={"reason": reason[:240]},
        )
    )


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _plan_for_variant(variant_id: str | int | None) -> str:
    normalized = str(variant_id or "")
    configured = (
        (str(current_app.config.get("LEMONSQUEEZY_CREATOR_VARIANT_ID", "")), "creator"),
        (str(current_app.config.get("LEMONSQUEEZY_STUDIO_VARIANT_ID", "")), "studio"),
    )
    mapping = {configured_id: plan for configured_id, plan in configured if configured_id}
    return mapping.get(normalized, "creator")


def sync_subscription_event(payload: dict) -> Subscription | None:
    data = payload.get("data") or {}
    attributes = data.get("attributes") or {}
    provider_id = str(data.get("id") or "")
    if not provider_id:
        raise ValueError("Webhook subscription ID is missing.")

    subscription = Subscription.query.filter_by(provider_subscription_id=provider_id).first()
    custom_data = (payload.get("meta") or {}).get("custom_data") or {}
    organization_id = str(custom_data.get("organization_id") or "")
    if not subscription:
        if not organization_id or not db.session.get(Organization, organization_id):
            raise ValueError("Webhook cannot be linked to an organization.")
        subscription = Subscription(
            organization_id=organization_id,
            provider_subscription_id=provider_id,
            status=str(attributes.get("status") or "active"),
        )
        db.session.add(subscription)

    subscription.provider_customer_id = str(attributes.get("customer_id") or "") or None
    subscription.variant_id = str(attributes.get("variant_id") or "") or None
    subscription.plan_key = _plan_for_variant(subscription.variant_id)
    subscription.status = str(attributes.get("status") or subscription.status)
    subscription.renews_at = _parse_datetime(attributes.get("renews_at"))
    subscription.ends_at = _parse_datetime(attributes.get("ends_at"))
    return subscription


def apply_payment_event(payload: dict) -> None:
    data = payload.get("data") or {}
    attributes = data.get("attributes") or {}
    invoice_id = str(data.get("id") or "")
    provider_subscription_id = str(attributes.get("subscription_id") or "")
    subscription = Subscription.query.filter_by(
        provider_subscription_id=provider_subscription_id
    ).first()
    if not subscription:
        raise ValueError("Payment webhook arrived before its subscription could be linked.")
    credits = PLAN_CREDITS.get(subscription.plan_key, PLAN_CREDITS["creator"])
    grant_credits(
        subscription.organization_id,
        credits,
        event_type="subscription_grant",
        idempotency_key=f"lemonsqueezy:invoice:{invoice_id}:grant",
        metadata={"subscription_id": provider_subscription_id, "plan_key": subscription.plan_key},
    )


class LemonSqueezyClient:
    base_url = "https://api.lemonsqueezy.com/v1"

    def __init__(self) -> None:
        self.api_key = str(current_app.config.get("LEMONSQUEEZY_API_KEY", "")).strip()
        if not self.api_key:
            raise RuntimeError("Lemon Squeezy billing is not configured yet.")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
            },
            timeout=20,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def create_checkout(self, *, organization: Organization, user, plan_key: str) -> str:
        store_id = str(current_app.config.get("LEMONSQUEEZY_STORE_ID", "")).strip()
        variant_id = str(
            current_app.config.get(f"LEMONSQUEEZY_{plan_key.upper()}_VARIANT_ID", "")
        ).strip()
        if not store_id or not variant_id:
            raise RuntimeError(f"The {plan_key} checkout is not configured yet.")
        base_url = str(current_app.config.get("BASE_URL", "")).rstrip("/")
        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "product_options": {
                        "enabled_variants": [int(variant_id)],
                        "redirect_url": f"{base_url}/app/billing?checkout=success",
                    },
                    "checkout_data": {
                        "email": user.email,
                        "name": user.display_name,
                        "custom": {
                            "organization_id": organization.id,
                            "user_id": user.id,
                        },
                    },
                },
                "relationships": {
                    "store": {"data": {"type": "stores", "id": store_id}},
                    "variant": {"data": {"type": "variants", "id": variant_id}},
                },
            }
        }
        response = self._request("POST", "/checkouts", json=payload)
        return str(response["data"]["attributes"]["url"])

    def customer_portal_url(self, subscription: Subscription) -> str:
        response = self._request("GET", f"/subscriptions/{subscription.provider_subscription_id}")
        return str(response["data"]["attributes"]["urls"]["customer_portal"])
