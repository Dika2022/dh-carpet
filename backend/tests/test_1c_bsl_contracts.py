import json
from pathlib import Path

import pytest

from app.schemas.stage3 import OneCBulkImportRequest

ROOT = Path(__file__).parents[2]
ONE_C = ROOT / "integrations" / "1c"


def test_confirmed_metadata_fixture_and_adapters_are_exact() -> None:
    metadata = json.loads((ONE_C / "tests" / "confirmed-metadata.json").read_text(encoding="utf-8"))
    adapters = {
        "sale": (ONE_C / "SalesAdapter.bsl").read_text(encoding="utf-8"),
        "customer_return": (ONE_C / "CustomerReturnsAdapter.bsl").read_text(encoding="utf-8"),
    }

    for event_type, code in adapters.items():
        fixture = metadata[event_type]
        assert fixture["document"] + "." + fixture["table_part"] in code
        assert fixture["operation"] in code
        assert f"СсылкаДокумента.{fixture['counterparty_field']}" in code
        assert f"СсылкаДокумента.{fixture['operation_field']}" in code
        for field in metadata["line_fields"]:
            assert field in code
        assert "УникальныйИдентификатор()" in code
        assert 'Вставить("document_snapshots"' in code
        assert "НомерСтроки" not in code


def test_document_snapshot_contract_requires_complete_line_set() -> None:
    base_event = {
        "barcode": "TEST-BARCODE",
        "event_type": "sale",
        "event_at": "2026-08-17T12:00:00+03:00",
        "price": "1000",
        "qty": "1",
        "source_ref": "11111111-1111-4111-8111-111111111111",
        "source_line_key": "22222222-2222-4222-8222-222222222222",
    }
    valid = OneCBulkImportRequest.model_validate({
        "mode": "incremental",
        "events": [base_event],
        "document_snapshots": [{
            "event_type": "sale",
            "source_ref": base_event["source_ref"],
            "posted": True,
            "line_keys": [base_event["source_line_key"]],
        }],
    })
    assert valid.document_snapshots[0].line_keys == [base_event["source_line_key"]]

    invalid = valid.model_dump(mode="json")
    invalid["document_snapshots"][0]["line_keys"] = ["another-line"]
    with pytest.raises(ValueError, match="полного snapshot"):
        OneCBulkImportRequest.model_validate(invalid)
