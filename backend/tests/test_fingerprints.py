from app.services.fingerprints import payload_fingerprint


def test_payload_fingerprint_is_deterministic_for_object_key_order() -> None:
    first = {"rug": {"barcode": "TEST-1", "name": "Ковёр"}, "version": 1}
    second = {"version": 1, "rug": {"name": "Ковёр", "barcode": "TEST-1"}}

    assert payload_fingerprint(first) == payload_fingerprint(second)


def test_payload_fingerprint_changes_with_payload() -> None:
    first = {"barcode": "TEST-1", "status": "available"}
    second = {"barcode": "TEST-1", "status": "sold"}

    assert payload_fingerprint(first) != payload_fingerprint(second)
