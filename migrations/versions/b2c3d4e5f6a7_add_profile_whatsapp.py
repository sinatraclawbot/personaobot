"""add whatsapp status/phone to profiles

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("whatsapp_status", sa.String(16), nullable=False, server_default=sa.text("''")))
    op.add_column("profiles", sa.Column("whatsapp_phone", sa.String(64), nullable=False, server_default=sa.text("''")))


def downgrade():
    op.drop_column("profiles", "whatsapp_phone")
    op.drop_column("profiles", "whatsapp_status")