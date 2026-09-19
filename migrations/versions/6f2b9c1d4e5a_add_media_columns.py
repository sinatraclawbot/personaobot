"""add message and draft media columns

Revision ID: 6f2b9c1d4e5a
Revises: 2aa924f185ec
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6f2b9c1d4e5a"
down_revision = "2aa924f185ec"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("media", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("drafts", sa.Column("media", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column("messages", "media")
    op.drop_column("drafts", "media")