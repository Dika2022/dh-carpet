"""Начальная схема данных.

Revision ID: 20260814_0001
Revises:
Create Date: 2026-08-14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rugs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("barcode", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barcode"),
    )
    op.create_index("ix_rugs_created_at", "rugs", ["created_at"], unique=False)

    op.create_table(
        "media_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "external_id", name="uq_media_items_source_external_id"
        ),
    )
    op.create_index(
        "ix_media_items_published_at",
        "media_items",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_media_items_created_at", "media_items", ["created_at"], unique=False
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("old_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_created_at",
        "audit_events",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "rug_external_data",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rug_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_rug_external_data_valid_period",
        ),
        sa.ForeignKeyConstraint(["rug_id"], ["rugs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rug_external_data_rug_id",
        "rug_external_data",
        ["rug_id"],
        unique=False,
    )

    op.create_table(
        "transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transcripts_media_item_id",
        "transcripts",
        ["media_item_id"],
        unique=False,
    )

    op.create_table(
        "rug_media_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rug_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_seconds", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("end_seconds", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_rug_media_links_confidence_range",
        ),
        sa.CheckConstraint(
            "end_seconds IS NULL OR "
            "(start_seconds IS NOT NULL AND end_seconds >= start_seconds)",
            name="ck_rug_media_links_end_after_start",
        ),
        sa.CheckConstraint(
            "start_seconds IS NULL OR start_seconds >= 0",
            name="ck_rug_media_links_start_seconds_nonnegative",
        ),
        sa.ForeignKeyConstraint(["rug_id"], ["rugs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rug_media_links_rug_id",
        "rug_media_links",
        ["rug_id"],
        unique=False,
    )
    op.create_index(
        "ix_rug_media_links_media_item_id",
        "rug_media_links",
        ["media_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_rug_media_links_verification_created_at",
        "rug_media_links",
        ["verification_status", "created_at"],
        unique=False,
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "end_seconds >= start_seconds",
            name="ck_transcript_segments_end_after_start",
        ),
        sa.CheckConstraint(
            "start_seconds >= 0",
            name="ck_transcript_segments_start_seconds_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"], ["transcripts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transcript_segments_transcript_id",
        "transcript_segments",
        ["transcript_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transcript_segments_transcript_id", table_name="transcript_segments"
    )
    op.drop_table("transcript_segments")
    op.drop_index(
        "ix_rug_media_links_verification_created_at", table_name="rug_media_links"
    )
    op.drop_index("ix_rug_media_links_media_item_id", table_name="rug_media_links")
    op.drop_index("ix_rug_media_links_rug_id", table_name="rug_media_links")
    op.drop_table("rug_media_links")
    op.drop_index("ix_transcripts_media_item_id", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_index(
        "ix_rug_external_data_rug_id", table_name="rug_external_data"
    )
    op.drop_table("rug_external_data")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_media_items_created_at", table_name="media_items")
    op.drop_index("ix_media_items_published_at", table_name="media_items")
    op.drop_table("media_items")
    op.drop_index("ix_rugs_created_at", table_name="rugs")
    op.drop_table("rugs")
