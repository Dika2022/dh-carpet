"""Каталог ковров, фотографии и fingerprint истории.

Revision ID: 20260814_0002
Revises: 20260814_0001
Create Date: 2026-08-14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0002"
down_revision: str | None = "20260814_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rugs", sa.Column("article", sa.String(length=100), nullable=True))
    op.add_column("rugs", sa.Column("country", sa.String(length=100), nullable=True))
    op.add_column("rugs", sa.Column("composition", sa.Text(), nullable=True))
    op.add_column(
        "rugs", sa.Column("width_cm", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    op.add_column(
        "rugs", sa.Column("length_cm", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    op.add_column(
        "rugs", sa.Column("current_location", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "rugs",
        sa.Column("retail_price", sa.Numeric(precision=14, scale=2), nullable=True),
    )
    op.add_column(
        "rugs",
        sa.Column("contractor_price", sa.Numeric(precision=14, scale=2), nullable=True),
    )
    op.add_column(
        "rugs",
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'RUB'"),
            nullable=False,
        ),
    )
    op.add_column(
        "rugs", sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_rugs_width_positive", "rugs", "width_cm IS NULL OR width_cm > 0"
    )
    op.create_check_constraint(
        "ck_rugs_length_positive", "rugs", "length_cm IS NULL OR length_cm > 0"
    )
    op.create_check_constraint(
        "ck_rugs_retail_price_nonnegative",
        "rugs",
        "retail_price IS NULL OR retail_price >= 0",
    )
    op.create_check_constraint(
        "ck_rugs_contractor_price_nonnegative",
        "rugs",
        "contractor_price IS NULL OR contractor_price >= 0",
    )
    op.create_index("ix_rugs_status", "rugs", ["status"], unique=False)
    op.create_index(
        "ix_rugs_current_location", "rugs", ["current_location"], unique=False
    )
    op.create_index("ix_rugs_article", "rugs", ["article"], unique=False)

    op.add_column(
        "rug_external_data",
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE rug_external_data "
        "SET fingerprint = md5(payload::text) "
        "WHERE fingerprint IS NULL"
    )
    op.alter_column("rug_external_data", "fingerprint", nullable=False)
    op.create_index(
        "ix_rug_external_data_fingerprint",
        "rug_external_data",
        ["rug_id", "source", "fingerprint"],
        unique=False,
    )
    op.execute(
        "WITH ranked AS ("
        "SELECT id, valid_from, "
        "max(valid_from) OVER (PARTITION BY rug_id, source) AS latest_valid_from, "
        "row_number() OVER ("
        "PARTITION BY rug_id, source "
        "ORDER BY valid_from DESC, created_at DESC, id DESC"
        ") AS row_number "
        "FROM rug_external_data WHERE valid_to IS NULL"
        ") "
        "UPDATE rug_external_data AS history "
        "SET valid_to = greatest(history.valid_from, ranked.latest_valid_from) "
        "FROM ranked "
        "WHERE history.id = ranked.id AND ranked.row_number > 1"
    )
    op.create_index(
        "uq_rug_external_data_current",
        "rug_external_data",
        ["rug_id", "source"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    op.create_table(
        "rug_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rug_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_rug_photos_sort_order_nonnegative"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_rug_photos_valid_period",
        ),
        sa.ForeignKeyConstraint(["rug_id"], ["rugs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rug_photos_rug_current_sort",
        "rug_photos",
        ["rug_id", "is_current", "sort_order"],
        unique=False,
    )
    op.create_index(
        "ix_rug_photos_source_external_id",
        "rug_photos",
        ["source", "external_id"],
        unique=False,
    )
    op.create_index(
        "ix_rug_photos_checksum", "rug_photos", ["checksum"], unique=False
    )
    op.create_index(
        "uq_rug_photos_current_fingerprint",
        "rug_photos",
        ["rug_id", "source", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("is_current IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_rug_photos_current_fingerprint", table_name="rug_photos")
    op.drop_index("ix_rug_photos_checksum", table_name="rug_photos")
    op.drop_index("ix_rug_photos_source_external_id", table_name="rug_photos")
    op.drop_index("ix_rug_photos_rug_current_sort", table_name="rug_photos")
    op.drop_table("rug_photos")

    op.drop_index("uq_rug_external_data_current", table_name="rug_external_data")
    op.drop_index("ix_rug_external_data_fingerprint", table_name="rug_external_data")
    op.drop_column("rug_external_data", "fingerprint")

    op.drop_index("ix_rugs_article", table_name="rugs")
    op.drop_index("ix_rugs_current_location", table_name="rugs")
    op.drop_index("ix_rugs_status", table_name="rugs")
    op.drop_constraint(
        "ck_rugs_contractor_price_nonnegative", "rugs", type_="check"
    )
    op.drop_constraint("ck_rugs_retail_price_nonnegative", "rugs", type_="check")
    op.drop_constraint("ck_rugs_length_positive", "rugs", type_="check")
    op.drop_constraint("ck_rugs_width_positive", "rugs", type_="check")
    op.drop_column("rugs", "source_updated_at")
    op.drop_column("rugs", "currency")
    op.drop_column("rugs", "contractor_price")
    op.drop_column("rugs", "retail_price")
    op.drop_column("rugs", "current_location")
    op.drop_column("rugs", "length_cm")
    op.drop_column("rugs", "width_cm")
    op.drop_column("rugs", "composition")
    op.drop_column("rugs", "country")
    op.drop_column("rugs", "article")
