"""add billing webhook inbox

Revision ID: 4f0f8e5f3c21
Revises: ce098b26757f
Create Date: 2026-07-20 23:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "4f0f8e5f3c21"
down_revision = "ce098b26757f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_webhooks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_name", sa.String(length=80), nullable=False),
        sa.Column("provider_object_id", sa.String(length=120), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("billing_webhooks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_billing_webhooks_event_name"), ["event_name"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_billing_webhooks_provider_object_id"),
            ["provider_object_id"],
            unique=False,
        )
        batch_op.create_index(batch_op.f("ix_billing_webhooks_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_billing_webhooks_payload_hash"), ["payload_hash"], unique=True)


def downgrade():
    with op.batch_alter_table("billing_webhooks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_billing_webhooks_payload_hash"))
        batch_op.drop_index(batch_op.f("ix_billing_webhooks_status"))
        batch_op.drop_index(batch_op.f("ix_billing_webhooks_provider_object_id"))
        batch_op.drop_index(batch_op.f("ix_billing_webhooks_event_name"))
    op.drop_table("billing_webhooks")
