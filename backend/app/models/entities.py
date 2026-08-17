import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.enums import (
    RugCategory,
    RugMediaLinkSource,
    RugStatus,
    VerificationStatus,
)


class Rug(Base):
    __tablename__ = "rugs"
    __table_args__ = (
        CheckConstraint("width_cm IS NULL OR width_cm > 0", name="ck_rugs_width_positive"),
        CheckConstraint(
            "length_cm IS NULL OR length_cm > 0", name="ck_rugs_length_positive"
        ),
        CheckConstraint(
            "retail_price IS NULL OR retail_price >= 0",
            name="ck_rugs_retail_price_nonnegative",
        ),
        CheckConstraint(
            "contractor_price IS NULL OR contractor_price >= 0",
            name="ck_rugs_contractor_price_nonnegative",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR weight_kg >= 0", name="ck_rugs_weight_nonnegative"
        ),
        CheckConstraint("stock_qty >= 0", name="ck_rugs_stock_nonnegative"),
        Index("ix_rugs_created_at", "created_at"),
        Index("ix_rugs_status", "status"),
        Index("ix_rugs_current_location", "current_location"),
        Index("ix_rugs_article", "article"),
        Index(
            "uq_rugs_article_not_null",
            "article",
            unique=True,
            postgresql_where=sql_text("article IS NOT NULL"),
        ),
        Index("ix_rugs_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    barcode: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default=RugStatus.UNKNOWN.value, nullable=False
    )
    article: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    composition: Mapped[str | None] = mapped_column(Text)
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    current_location: Mapped[str | None] = mapped_column(String(255))
    retail_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    contractor_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(
        String(3), default="RUB", server_default=sql_text("'RUB'"), nullable=False
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    category: Mapped[str] = mapped_column(
        String(50), default=RugCategory.RUG.value, server_default="rug", nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    stock_qty: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=0, server_default="0", nullable=False
    )
    stock_unit: Mapped[str | None] = mapped_column(String(50))
    retail_price_unit: Mapped[str | None] = mapped_column(String(50))
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    photos: Mapped[list["RugPhoto"]] = relationship(back_populates="rug")
    external_versions: Mapped[list["RugExternalData"]] = relationship(
        back_populates="rug"
    )

    @validates("status")
    def validate_status(self, _key: str, value: str | RugStatus) -> str:
        return RugStatus(value).value

    @validates("category")
    def validate_category(self, _key: str, value: str | RugCategory) -> str:
        return RugCategory(value).value


class RugExternalData(Base):
    __tablename__ = "rug_external_data"
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_rug_external_data_valid_period",
        ),
        Index("ix_rug_external_data_rug_id", "rug_id"),
        Index(
            "ix_rug_external_data_fingerprint",
            "rug_id",
            "source",
            "fingerprint",
        ),
        Index(
            "uq_rug_external_data_current",
            "rug_id",
            "source",
            unique=True,
            postgresql_where=sql_text("valid_to IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rugs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rug: Mapped[Rug] = relationship(back_populates="external_versions")


class RugPhoto(Base):
    __tablename__ = "rug_photos"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_rug_photos_sort_order_nonnegative"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_rug_photos_valid_period",
        ),
        Index("ix_rug_photos_rug_current_sort", "rug_id", "is_current", "sort_order"),
        Index("ix_rug_photos_source_external_id", "source", "external_id"),
        Index("ix_rug_photos_checksum", "checksum"),
        Index(
            "uq_rug_photos_current_fingerprint",
            "rug_id",
            "source",
            "fingerprint",
            unique=True,
            postgresql_where=sql_text("is_current IS TRUE"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rugs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    local_path: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sql_text("true"), nullable=False
    )
    checksum: Mapped[str | None] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rug: Mapped[Rug] = relationship(back_populates="photos")


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_media_items_source_external_id"),
        Index("ix_media_items_published_at", "published_at"),
        Index("ix_media_items_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(50), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    local_path: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (Index("ix_transcripts_media_item_id", "media_item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    media_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        CheckConstraint(
            "start_seconds >= 0",
            name="ck_transcript_segments_start_seconds_nonnegative",
        ),
        CheckConstraint(
            "end_seconds >= start_seconds",
            name="ck_transcript_segments_end_after_start",
        ),
        Index("ix_transcript_segments_transcript_id", "transcript_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class RugMediaLink(Base):
    __tablename__ = "rug_media_links"
    __table_args__ = (
        CheckConstraint(
            "start_seconds IS NULL OR start_seconds >= 0",
            name="ck_rug_media_links_start_seconds_nonnegative",
        ),
        CheckConstraint(
            "end_seconds IS NULL OR "
            "(start_seconds IS NOT NULL AND end_seconds >= start_seconds)",
            name="ck_rug_media_links_end_after_start",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_rug_media_links_confidence_range",
        ),
        Index("ix_rug_media_links_rug_id", "rug_id"),
        Index("ix_rug_media_links_media_item_id", "media_item_id"),
        Index(
            "ix_rug_media_links_verification_created_at",
            "verification_status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rugs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    media_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    start_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(50), default=VerificationStatus.UNVERIFIED.value, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @validates("source")
    def validate_source(self, _key: str, value: str | RugMediaLinkSource) -> str:
        return RugMediaLinkSource(value).value

    @validates("verification_status")
    def validate_verification_status(
        self, _key: str, value: str | VerificationStatus
    ) -> str:
        return VerificationStatus(value).value


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255))
    old_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RugLocation(Base):
    __tablename__ = "rug_locations"
    __table_args__ = (
        CheckConstraint("qty >= 0", name="ck_rug_locations_qty_nonnegative"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_rug_locations_valid_period",
        ),
        Index("ix_rug_locations_rug_current", "rug_id", "is_current"),
        Index("ix_rug_locations_warehouse_cell", "warehouse", "cell"),
        Index(
            "uq_rug_locations_current_fingerprint",
            "rug_id",
            "fingerprint",
            unique=True,
            postgresql_where=sql_text("is_current IS TRUE"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rugs.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    cell: Mapped[str | None] = mapped_column(String(255))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sql_text("true"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RugEvent(Base):
    __tablename__ = "rug_events"
    __table_args__ = (
        CheckConstraint("price IS NULL OR price >= 0", name="ck_rug_events_price_nonnegative"),
        CheckConstraint(
            "old_price IS NULL OR old_price >= 0",
            name="ck_rug_events_old_price_nonnegative",
        ),
        CheckConstraint("qty IS NULL OR qty >= 0", name="ck_rug_events_qty_nonnegative"),
        CheckConstraint(
            "discount_value IS NULL OR discount_value >= 0",
            name="ck_rug_events_discount_nonnegative",
        ),
        CheckConstraint(
            "retail_price_at_event IS NULL OR retail_price_at_event >= 0",
            name="ck_rug_events_retail_at_event_nonnegative",
        ),
        CheckConstraint(
            "calculated_price IS NULL OR calculated_price >= 0",
            name="ck_rug_events_calculated_nonnegative",
        ),
        CheckConstraint(
            "start_seconds IS NULL OR start_seconds >= 0",
            name="ck_rug_events_start_nonnegative",
        ),
        CheckConstraint(
            "end_seconds IS NULL OR (start_seconds IS NOT NULL AND end_seconds >= start_seconds)",
            name="ck_rug_events_end_after_start",
        ),
        Index("ix_rug_events_rug_event_at", "rug_id", "event_at"),
        Index("ix_rug_events_type_status", "event_type", "status"),
        Index("ix_rug_events_media_item_id", "media_item_id"),
        Index("ix_rug_events_source_ref", "source", "source_ref"),
        Index(
            "uq_rug_events_source_line",
            "source",
            "event_type",
            "source_ref",
            "source_line_key",
            unique=True,
            postgresql_where=sql_text("source_ref IS NOT NULL AND source_line_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rugs.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default="RUB", nullable=False)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(50))
    counterparty: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255))
    source_line_key: Mapped[str | None] = mapped_column(String(255))
    document_number: Mapped[str | None] = mapped_column(String(100))
    media_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_items.id", ondelete="RESTRICT")
    )
    start_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    discount_type: Mapped[str | None] = mapped_column(String(50))
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    retail_price_at_event: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    calculated_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_path: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_runs_source_started", "source", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_items: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    succeeded_items: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    failed_items: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class SyncItem(Base):
    __tablename__ = "sync_items"
    __table_args__ = (
        UniqueConstraint("sync_run_id", "entity_type", "source_key", name="uq_sync_items_run_entity_key"),
        Index("ix_sync_items_run_status", "sync_run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sync_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[str | None] = mapped_column(String(50))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExternalPhotoFile(Base):
    __tablename__ = "external_photo_files"
    __table_args__ = (
        Index(
            "uq_external_photo_files_current_path",
            "source",
            "relative_path",
            unique=True,
            postgresql_where=sql_text("is_current IS TRUE"),
        ),
        Index("ix_external_photo_files_rug_current", "rug_id", "is_current"),
        Index("ix_external_photo_files_checksum", "checksum"),
        Index("ix_external_photo_files_article", "article"),
        UniqueConstraint(
            "source", "rug_id", "checksum", name="uq_external_photo_files_rug_checksum"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rugs.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    article: Mapped[str] = mapped_column(String(100), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
