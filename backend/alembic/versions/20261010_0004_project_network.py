"""project network (groups on one topic)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10 10:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('network', sa.String(length=255), nullable=True))
    op.create_index('ix_projects_network', 'projects', ['network'])


def downgrade() -> None:
    op.drop_index('ix_projects_network', table_name='projects')
    op.drop_column('projects', 'network')
