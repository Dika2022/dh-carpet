import uuid

import pytest
from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app import models  # noqa: F401
from app.db.base import Base
from app.models.entities import Rug, RugMediaLink
from app.models.enums import RugMediaLinkSource, RugStatus, VerificationStatus


EXPECTED_TABLES = {
    "rugs",
    "rug_external_data",
    "media_items",
    "transcripts",
    "transcript_segments",
    "rug_media_links",
    "audit_events",
}

TIMEZONE_COLUMNS = {
    "rugs": {"created_at", "updated_at"},
    "rug_external_data": {"valid_from", "valid_to", "created_at"},
    "media_items": {"published_at", "created_at"},
    "transcripts": {"created_at"},
    "rug_media_links": {"created_at"},
    "audit_events": {"created_at"},
}

EXPECTED_INDEXES = {
    "rugs": {"ix_rugs_created_at"},
    "rug_external_data": {"ix_rug_external_data_rug_id"},
    "media_items": {"ix_media_items_published_at", "ix_media_items_created_at"},
    "transcripts": {"ix_transcripts_media_item_id"},
    "transcript_segments": {"ix_transcript_segments_transcript_id"},
    "rug_media_links": {
        "ix_rug_media_links_rug_id",
        "ix_rug_media_links_media_item_id",
        "ix_rug_media_links_verification_created_at",
    },
    "audit_events": {"ix_audit_events_entity", "ix_audit_events_created_at"},
}


def test_all_primary_keys_are_application_generated_uuids() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    for table in Base.metadata.tables.values():
        primary_key_columns = list(table.primary_key.columns)
        assert [column.name for column in primary_key_columns] == ["id"]
        assert isinstance(primary_key_columns[0].type, UUID)
        assert primary_key_columns[0].default is not None
        assert primary_key_columns[0].default.is_callable


def test_audit_identifiers_have_expected_types_and_links() -> None:
    table = Base.metadata.tables["audit_events"]
    assert isinstance(table.c.entity_id.type, UUID)
    assert not table.c.entity_id.foreign_keys
    assert not table.c.actor_id.foreign_keys


def test_all_business_timestamps_are_timezone_aware() -> None:
    for table_name, column_names in TIMEZONE_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        for column_name in column_names:
            column_type = table.c[column_name].type
            assert isinstance(column_type, DateTime)
            assert column_type.timezone is True


def test_historical_foreign_keys_restrict_deletion() -> None:
    foreign_keys = {
        foreign_key
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
    }
    assert foreign_keys
    assert {foreign_key.ondelete for foreign_key in foreign_keys} == {"RESTRICT"}


def test_expected_unique_constraints_and_indexes_exist() -> None:
    rugs = Base.metadata.tables["rugs"]
    media_items = Base.metadata.tables["media_items"]

    rug_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in rugs.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    media_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in media_items.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("barcode",) in rug_unique_columns
    assert ("source", "external_id") in media_unique_columns

    for table_name, expected_names in EXPECTED_INDEXES.items():
        actual_names = {index.name for index in Base.metadata.tables[table_name].indexes}
        assert actual_names == expected_names


def test_expected_check_constraints_exist() -> None:
    expected_names = {
        "ck_rug_external_data_valid_period",
        "ck_transcript_segments_start_seconds_nonnegative",
        "ck_transcript_segments_end_after_start",
        "ck_rug_media_links_start_seconds_nonnegative",
        "ck_rug_media_links_end_after_start",
        "ck_rug_media_links_confidence_range",
    }
    actual_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name is not None and constraint.name.startswith("ck_")
    }
    assert actual_names == expected_names


def test_application_enums_have_initial_values() -> None:
    assert {value.value for value in RugStatus} == {
        "available",
        "sold",
        "withdrawn",
        "unknown",
    }
    assert {value.value for value in RugMediaLinkSource} == {
        "ai",
        "manager",
        "admin",
        "import",
    }
    assert {value.value for value in VerificationStatus} == {
        "unverified",
        "verified",
        "rejected",
    }

    with pytest.raises(ValueError):
        Rug(id=uuid.uuid4(), barcode="test", name="test", status="invalid")
    with pytest.raises(ValueError):
        RugMediaLink(
            id=uuid.uuid4(),
            rug_id=uuid.uuid4(),
            media_item_id=uuid.uuid4(),
            source="invalid",
            verification_status="unverified",
        )
