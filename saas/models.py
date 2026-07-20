"""Persistent SaaS domain models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from werkzeug.security import check_password_hash, generate_password_hash

from saas.extensions import db


def new_id() -> str:
    return uuid.uuid4().hex


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    email = db.Column(db.String(320), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="active", index=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status,
            "email_verified": self.email_verified,
            "created_at": self.created_at.isoformat(),
        }


class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "slug": self.slug}


class Membership(db.Model):
    __tablename__ = "memberships"
    __table_args__ = (db.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),)

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    organization_id = db.Column(
        db.String(32), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(db.String(32), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(24), nullable=False, default="member")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    organization = db.relationship("Organization", lazy="joined")
    user = db.relationship("User", lazy="joined")


class Project(db.Model):
    __tablename__ = "projects"
    __table_args__ = (db.UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),)

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    organization_id = db.Column(
        db.String(32), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id = db.Column(db.String(32), db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    slug = db.Column(db.String(260), nullable=False)
    workflow_type = db.Column(db.String(40), nullable=False, default="audio_translate", index=True)
    source_language = db.Column(db.String(16), nullable=False, default="auto")
    target_languages = db.Column(db.JSON, nullable=False, default=list)
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    duration_seconds = db.Column(db.Float, nullable=True)
    rights_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    voice_consent_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    organization = db.relationship("Organization", lazy="joined")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "title": self.title,
            "slug": self.slug,
            "workflow_type": self.workflow_type,
            "source_language": self.source_language,
            "target_languages": list(self.target_languages or []),
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "rights_confirmed": self.rights_confirmed,
            "voice_consent_confirmed": self.voice_consent_confirmed,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Artifact(db.Model):
    __tablename__ = "artifacts"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(
        db.String(32), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id = db.Column(db.String(32), db.ForeignKey("pipeline_jobs.id", ondelete="SET NULL"), nullable=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    storage_key = db.Column(db.String(1024), nullable=False, unique=True)
    original_filename = db.Column(db.String(512), nullable=True)
    content_type = db.Column(db.String(160), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    language = db.Column(db.String(16), nullable=True)
    artifact_metadata = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "kind": self.kind,
            "storage_key": self.storage_key,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "language": self.language,
            "metadata": self.artifact_metadata or {},
            "created_at": self.created_at.isoformat(),
        }


class PipelineJob(db.Model):
    __tablename__ = "pipeline_jobs"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(
        db.String(32), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id = db.Column(db.String(32), db.ForeignKey("users.id"), nullable=False, index=True)
    mode = db.Column(db.String(24), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="queued", index=True)
    stage = db.Column(db.String(80), nullable=False, default="queued")
    progress_percent = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text, nullable=True)
    result = db.Column(db.JSON, nullable=True)
    queue_job_id = db.Column(db.String(80), nullable=True)
    idempotency_key = db.Column(db.String(120), nullable=True, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = db.relationship("Project", lazy="joined")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "mode": self.mode,
            "status": self.status,
            "stage": self.stage,
            "progress_percent": self.progress_percent,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "updated_at": self.updated_at.isoformat(),
        }


class VoiceConsent(db.Model):
    __tablename__ = "voice_consents"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(
        db.String(32), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirmed_by_user_id = db.Column(db.String(32), db.ForeignKey("users.id"), nullable=False)
    speaker_name = db.Column(db.String(160), nullable=False, default="Primary narrator")
    declaration_version = db.Column(db.String(32), nullable=False, default="2026-07-20")
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    confirmed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)


class UsageEvent(db.Model):
    __tablename__ = "usage_events"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    organization_id = db.Column(
        db.String(32), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = db.Column(db.String(32), db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    job_id = db.Column(db.String(32), db.ForeignKey("pipeline_jobs.id", ondelete="SET NULL"), nullable=True)
    event_type = db.Column(db.String(32), nullable=False, index=True)
    credits = db.Column(db.Integer, nullable=False)
    idempotency_key = db.Column(db.String(160), nullable=False, unique=True)
    event_metadata = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    organization_id = db.Column(
        db.String(32), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = db.Column(db.String(32), nullable=False, default="lemonsqueezy")
    provider_subscription_id = db.Column(db.String(120), nullable=False, unique=True)
    provider_customer_id = db.Column(db.String(120), nullable=True, index=True)
    variant_id = db.Column(db.String(80), nullable=True)
    plan_key = db.Column(db.String(40), nullable=False, default="creator")
    status = db.Column(db.String(40), nullable=False, index=True)
    renews_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "plan_key": self.plan_key,
            "status": self.status,
            "renews_at": self.renews_at.isoformat() if self.renews_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
        }


class BillingWebhook(db.Model):
    __tablename__ = "billing_webhooks"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    provider = db.Column(db.String(32), nullable=False, default="lemonsqueezy")
    event_name = db.Column(db.String(80), nullable=False, index=True)
    provider_object_id = db.Column(db.String(120), nullable=True, index=True)
    payload_hash = db.Column(db.String(64), nullable=False, unique=True)
    event_payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="received", index=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    processed_at = db.Column(db.DateTime(timezone=True), nullable=True)
