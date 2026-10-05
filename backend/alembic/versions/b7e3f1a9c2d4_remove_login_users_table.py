"""remove login: drop users table and user FKs

Revision ID: b7e3f1a9c2d4
Revises: d50c12bdb5c9
Create Date: 2026-10-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b7e3f1a9c2d4'
down_revision = 'd50c12bdb5c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('fk_stock_movement_user_id_users', 'stock_movement', type_='foreignkey')
    op.drop_constraint('fk_agency_booking_created_by_users', 'agency_booking', type_='foreignkey')
    op.drop_constraint('fk_work_order_created_by_users', 'work_order', type_='foreignkey')
    op.drop_constraint('fk_alert_acked_by_users', 'alert', type_='foreignkey')
    op.drop_constraint('fk_audit_log_actor_id_users', 'audit_log', type_='foreignkey')
    op.drop_table('users')
    op.execute(sa.text("DROP TYPE IF EXISTS user_role CASCADE"))


def downgrade() -> None:
    op.execute(sa.text("DROP TYPE IF EXISTS user_role CASCADE"))
    op.execute(sa.text("CREATE TYPE user_role AS ENUM ('commander', 'maintenance_officer', 'viewer')"))
    user_role = postgresql.ENUM('commander', 'maintenance_officer', 'viewer', name='user_role', create_type=False)
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=48), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=96), nullable=False),
        sa.Column('role', user_role, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
        sa.UniqueConstraint('username', name=op.f('uq_users_username')),
    )
    op.create_foreign_key(
        op.f('fk_audit_log_actor_id_users'), 'audit_log', 'users',
        ['actor_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        op.f('fk_alert_acked_by_users'), 'alert', 'users',
        ['acked_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        op.f('fk_work_order_created_by_users'), 'work_order', 'users',
        ['created_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        op.f('fk_agency_booking_created_by_users'), 'agency_booking', 'users',
        ['created_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        op.f('fk_stock_movement_user_id_users'), 'stock_movement', 'users',
        ['user_id'], ['id'], ondelete='SET NULL',
    )
