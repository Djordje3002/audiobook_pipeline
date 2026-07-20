"""add creator-selected project workflow

Revision ID: 91b2a6e4d883
Revises: 4f0f8e5f3c21
Create Date: 2026-07-20 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "91b2a6e4d883"
down_revision = "4f0f8e5f3c21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "workflow_type",
            sa.String(length=40),
            nullable=False,
            server_default="audio_translate",
        ),
    )
    op.create_index("ix_projects_workflow_type", "projects", ["workflow_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_projects_workflow_type", table_name="projects")
    op.drop_column("projects", "workflow_type")
