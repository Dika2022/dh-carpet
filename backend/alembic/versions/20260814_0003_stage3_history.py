"""Интеграция 1С, местонахождения, события и внешний фотоархив.

Revision ID: 20260814_0003
Revises: 20260814_0002
Create Date: 2026-08-14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0003"
down_revision: str | None = "20260814_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rugs", sa.Column("category", sa.String(50), server_default="rug", nullable=False))
    op.add_column("rugs", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("rugs", sa.Column("weight_kg", sa.Numeric(12, 3), nullable=True))
    op.add_column("rugs", sa.Column("stock_qty", sa.Numeric(14, 3), server_default="0", nullable=False))
    op.add_column("rugs", sa.Column("stock_unit", sa.String(50), nullable=True))
    op.add_column("rugs", sa.Column("retail_price_unit", sa.String(50), nullable=True))
    op.add_column("rugs", sa.Column("attributes", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.create_check_constraint("ck_rugs_weight_nonnegative", "rugs", "weight_kg IS NULL OR weight_kg >= 0")
    op.create_check_constraint("ck_rugs_stock_nonnegative", "rugs", "stock_qty >= 0")
    op.create_index("ix_rugs_category", "rugs", ["category"])
    op.create_index("uq_rugs_article_not_null", "rugs", ["article"], unique=True, postgresql_where=sa.text("article IS NOT NULL"))

    op.create_table(
        "rug_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rug_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse", sa.String(255), nullable=False),
        sa.Column("cell", sa.String(255), nullable=True),
        sa.Column("qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("qty >= 0", name="ck_rug_locations_qty_nonnegative"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="ck_rug_locations_valid_period"),
        sa.ForeignKeyConstraint(["rug_id"], ["rugs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rug_locations_rug_current", "rug_locations", ["rug_id", "is_current"])
    op.create_index("ix_rug_locations_warehouse_cell", "rug_locations", ["warehouse", "cell"])
    op.create_index("uq_rug_locations_current_fingerprint", "rug_locations", ["rug_id", "fingerprint"], unique=True, postgresql_where=sa.text("is_current IS TRUE"))

    op.create_table(
        "rug_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rug_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=True),
        sa.Column("old_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), server_default="RUB", nullable=False),
        sa.Column("qty", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("counterparty", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("source_line_key", sa.String(255), nullable=True),
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("end_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("discount_type", sa.String(50), nullable=True),
        sa.Column("discount_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("retail_price_at_event", sa.Numeric(14, 2), nullable=True),
        sa.Column("calculated_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("page_path", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_rug_events_price_nonnegative"),
        sa.CheckConstraint("old_price IS NULL OR old_price >= 0", name="ck_rug_events_old_price_nonnegative"),
        sa.CheckConstraint("qty IS NULL OR qty >= 0", name="ck_rug_events_qty_nonnegative"),
        sa.CheckConstraint("discount_value IS NULL OR discount_value >= 0", name="ck_rug_events_discount_nonnegative"),
        sa.CheckConstraint("retail_price_at_event IS NULL OR retail_price_at_event >= 0", name="ck_rug_events_retail_at_event_nonnegative"),
        sa.CheckConstraint("calculated_price IS NULL OR calculated_price >= 0", name="ck_rug_events_calculated_nonnegative"),
        sa.CheckConstraint("start_seconds IS NULL OR start_seconds >= 0", name="ck_rug_events_start_nonnegative"),
        sa.CheckConstraint("end_seconds IS NULL OR (start_seconds IS NOT NULL AND end_seconds >= start_seconds)", name="ck_rug_events_end_after_start"),
        sa.ForeignKeyConstraint(["rug_id"], ["rugs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_item_id"], ["media_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rug_events_rug_event_at", "rug_events", ["rug_id", "event_at"])
    op.create_index("ix_rug_events_type_status", "rug_events", ["event_type", "status"])
    op.create_index("ix_rug_events_media_item_id", "rug_events", ["media_item_id"])
    op.create_index("ix_rug_events_source_ref", "rug_events", ["source", "source_ref"])
    op.create_index("uq_rug_events_source_line", "rug_events", ["source", "event_type", "source_ref", "source_line_key"], unique=True, postgresql_where=sa.text("source_ref IS NOT NULL AND source_line_key IS NOT NULL"))

    op.create_table(
        "sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("succeeded_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_runs_source_started", "sync_runs", ["source", "started_at"])
    op.create_table(
        "sync_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sync_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("source_key", sa.String(500), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("result", sa.String(50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sync_run_id", "entity_type", "source_key", name="uq_sync_items_run_entity_key"),
    )
    op.create_index("ix_sync_items_run_status", "sync_items", ["sync_run_id", "status"])

    op.create_table(
        "external_photo_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rug_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("article", sa.String(100), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rug_id"], ["rugs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "rug_id", "checksum", name="uq_external_photo_files_rug_checksum"),
    )
    op.create_index("ix_external_photo_files_rug_current", "external_photo_files", ["rug_id", "is_current"])
    op.create_index("ix_external_photo_files_checksum", "external_photo_files", ["checksum"])
    op.create_index("ix_external_photo_files_article", "external_photo_files", ["article"])
    op.create_index("uq_external_photo_files_current_path", "external_photo_files", ["source", "relative_path"], unique=True, postgresql_where=sa.text("is_current IS TRUE"))


def downgrade() -> None:
    op.drop_table("external_photo_files")
    op.drop_table("sync_items")
    op.drop_table("sync_runs")
    op.drop_table("rug_events")
    op.drop_table("rug_locations")
    op.drop_index("uq_rugs_article_not_null", table_name="rugs")
    op.drop_index("ix_rugs_category", table_name="rugs")
    op.drop_constraint("ck_rugs_stock_nonnegative", "rugs", type_="check")
    op.drop_constraint("ck_rugs_weight_nonnegative", "rugs", type_="check")
    for column in ("attributes", "retail_price_unit", "stock_unit", "stock_qty", "weight_kg", "description", "category"):
        op.drop_column("rugs", column)
