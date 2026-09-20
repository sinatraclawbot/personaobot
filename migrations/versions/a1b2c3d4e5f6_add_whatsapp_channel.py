"""add whatsapp channel columns to conversations

Revision ID: a1b2c3d4e5f6
Revises: 6f2b9c1d4e5a
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "6f2b9c1d4e5a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("channel", sa.String(16), nullable=False, server_default=sa.text("'telegram'")))
    op.add_column("conversations", sa.Column("whatsapp_chat_id", sa.String(128), nullable=True))


def downgrade():
    op.drop_column("conversations", "whatsapp_chat_id")
    op.drop_column("conversations", "channel")