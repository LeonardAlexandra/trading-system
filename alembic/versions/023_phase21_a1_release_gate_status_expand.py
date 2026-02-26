"""Phase2.1 A1: release_gate.status 五态扩展

Revision ID: 023
Revises: 022
Create Date: 2026-02-26

目标：
- 扩展 release_gate.status 可存储五态：
  candidate | approved | active | disabled | rollback
- 默认值为 candidate
- 仅做 A1 状态字段迁移，不改其他模块语义
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None

TARGET_TABLE = "release_gate"
STATUS_COLUMN = "status"
CHECK_NAME = "ck_release_gate_status_phase21_a1"
ALLOWED_STATES = ("candidate", "approved", "active", "disabled", "rollback")


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return table_name in inspect(bind).get_table_names()


def _column_exists(bind: sa.engine.Connection, table_name: str, column_name: str) -> bool:
    columns = inspect(bind).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def _get_column_type(bind: sa.engine.Connection, table_name: str, column_name: str):
    for col in inspect(bind).get_columns(table_name):
        if col["name"] == column_name:
            return col["type"]
    return None


def _check_exists(bind: sa.engine.Connection, table_name: str, check_name: str) -> bool:
    checks = inspect(bind).get_check_constraints(table_name)
    return any(chk.get("name") == check_name for chk in checks)


def _is_enum_type(column_type: object) -> bool:
    enums = getattr(column_type, "enums", None)
    return isinstance(enums, (list, tuple))


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _upgrade_postgres_enum(bind: sa.engine.Connection, column_type: object) -> None:
    enum_name = getattr(column_type, "name", None)
    enum_schema = getattr(column_type, "schema", None)
    existing_values = set(getattr(column_type, "enums", []) or [])
    if not enum_name:
        return

    qualified_enum_name = _quote_ident(enum_name)
    if enum_schema:
        qualified_enum_name = f"{_quote_ident(enum_schema)}.{qualified_enum_name}"

    for state in ALLOWED_STATES:
        if state in existing_values:
            continue
        op.execute(f"ALTER TYPE {qualified_enum_name} ADD VALUE IF NOT EXISTS '{state}'")


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TARGET_TABLE):
        return
    if not _column_exists(bind, TARGET_TABLE, STATUS_COLUMN):
        return

    dialect = bind.dialect.name
    column_type = _get_column_type(bind, TARGET_TABLE, STATUS_COLUMN)

    if dialect == "postgresql" and _is_enum_type(column_type):
        _upgrade_postgres_enum(bind, column_type)
        op.execute(
            f"ALTER TABLE {TARGET_TABLE} ALTER COLUMN {STATUS_COLUMN} SET DEFAULT 'candidate'"
        )
    else:
        # 非 ENUM 场景（如 VARCHAR）增加 CHECK 约束并设置默认值。
        with op.batch_alter_table(TARGET_TABLE) as batch_op:
            batch_op.alter_column(
                STATUS_COLUMN,
                existing_type=column_type if column_type is not None else sa.String(length=32),
                server_default=sa.text("'candidate'"),
            )
            if not _check_exists(bind, TARGET_TABLE, CHECK_NAME):
                batch_op.create_check_constraint(
                    CHECK_NAME,
                    "status IN ('candidate','approved','active','disabled','rollback')",
                )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TARGET_TABLE):
        return
    if not _column_exists(bind, TARGET_TABLE, STATUS_COLUMN):
        return

    dialect = bind.dialect.name
    column_type = _get_column_type(bind, TARGET_TABLE, STATUS_COLUMN)

    if dialect == "postgresql" and _is_enum_type(column_type):
        # PostgreSQL 不支持直接删除 enum value；此处确保 downgrade 可执行。
        op.execute(
            f"ALTER TABLE {TARGET_TABLE} ALTER COLUMN {STATUS_COLUMN} DROP DEFAULT"
        )
    else:
        with op.batch_alter_table(TARGET_TABLE) as batch_op:
            if _check_exists(bind, TARGET_TABLE, CHECK_NAME):
                batch_op.drop_constraint(CHECK_NAME, type_="check")
            batch_op.alter_column(
                STATUS_COLUMN,
                existing_type=column_type if column_type is not None else sa.String(length=32),
                server_default=None,
            )
