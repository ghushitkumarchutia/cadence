"""
Aggressive tests for app.core.normalizer — PII masking, hash determinism, schema extraction.
"""
from __future__ import annotations

import pytest

from app.core.normalizer import (
    compute_payload_hash,
    compute_schema_hash,
    normalize_payload,
)

class TestNormalizePayload:
    def test_none_input_returns_none(self):
        assert normalize_payload(None) is None

    def test_empty_dict_returns_empty(self):
        assert normalize_payload({}) == {}

    def test_uuid_masked(self):
        result = normalize_payload({"id": "550e8400-e29b-41d4-a716-446655440000"})
        assert result["id"] == "__UUID__"

    def test_iso_timestamp_masked(self):
        result = normalize_payload({"ts": "2024-01-15T10:30:00Z"})
        assert result["ts"] == "__TIMESTAMP__"

    def test_numeric_id_masked(self):
        result = normalize_payload({"account": "1234567890"})
        assert result["account"] == "__NUMERIC_ID__"

    def test_email_masked(self):
        result = normalize_payload({"email": "john.doe@example.com"})
        assert result["email"] == "__EMAIL__"

    def test_jwt_masked(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = normalize_payload({"token": jwt})
        assert result["token"] == "__JWT__"

    def test_phone_masked(self):
        result = normalize_payload({"phone": "+1-555-123-4567"})
        assert result["phone"] == "__PHONE__"

    def test_ipv4_masked(self):
        result = normalize_payload({"ip": "192.168.1.1"})
        assert result["ip"] == "__IP__"

    def test_ipv6_masked(self):
        result = normalize_payload({"ip": "2001:0db8:85a3:0000:0000:8a2e:0370:7334"})
        assert result["ip"] == "__IP__"

    def test_non_pii_string_passes_through(self):
        result = normalize_payload({"status": "active"})
        assert result["status"] == "active"

    def test_numeric_values_pass_through(self):
        result = normalize_payload({"count": 42, "rate": 3.14, "flag": True})
        assert result == {"count": 42, "flag": True, "rate": 3.14}  # sorted keys

    def test_nested_dict_sorted_keys(self):
        result = normalize_payload({"z_key": "val", "a_key": "val"})
        keys = list(result.keys())
        assert keys == ["a_key", "z_key"]

    def test_array_normalization(self):
        result = normalize_payload({"emails": ["user@test.com", "other@test.com"]})
        assert result["emails"] == ["__EMAIL__", "__EMAIL__"]

    def test_deep_nesting_stops_at_max_depth(self):
        # Build a payload nested 12 levels deep (MAX_DEPTH=10)
        payload: dict = {"level0": "test@deep.com"}
        current = payload
        for i in range(1, 12):
            inner: dict = {f"level{i}": "test@deep.com"}
            current[f"nested{i}"] = inner
            current = inner

        result = normalize_payload(payload)
        assert result is not None  # Must not crash

    def test_mixed_pii_payload(self):
        payload = {
            "user_id": "550e8400-e29b-41d4-a716-446655440000",
            "email": "john@test.com",
            "created_at": "2024-01-15T10:30:00Z",
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "name": "John Doe",
            "score": 95.5,
        }
        result = normalize_payload(payload)
        assert result["user_id"] == "__UUID__"
        assert result["email"] == "__EMAIL__"
        assert result["created_at"] == "__TIMESTAMP__"
        assert result["token"] == "__JWT__"
        assert result["name"] == "John Doe"  # Not PII pattern
        assert result["score"] == 95.5


class TestComputePayloadHash:
    def test_determinism(self):
        payload = {"key": "value", "count": 42}
        h1 = compute_payload_hash(payload)
        h2 = compute_payload_hash(payload)
        assert h1 == h2

    def test_key_order_invariant(self):
        h1 = compute_payload_hash({"a": 1, "b": 2})
        h2 = compute_payload_hash({"b": 2, "a": 1})
        assert h1 == h2

    def test_none_payload_deterministic(self):
        h1 = compute_payload_hash(None)
        h2 = compute_payload_hash(None)
        assert h1 == h2
        assert len(h1) == 16

    def test_different_payloads_different_hashes(self):
        h1 = compute_payload_hash({"key": "value1"})
        h2 = compute_payload_hash({"key": "value2"})
        assert h1 != h2

    def test_hash_length(self):
        h = compute_payload_hash({"test": 123})
        assert len(h) == 16

class TestComputeSchemaHash:
    def test_determinism(self):
        payload = {"name": "John", "age": 30}
        h1 = compute_schema_hash(payload)
        h2 = compute_schema_hash(payload)
        assert h1 == h2

    def test_same_structure_different_values_same_hash(self):
        h1 = compute_schema_hash({"name": "John", "age": 30})
        h2 = compute_schema_hash({"name": "Jane", "age": 25})
        assert h1 == h2

    def test_different_structure_different_hash(self):
        h1 = compute_schema_hash({"name": "John"})
        h2 = compute_schema_hash({"name": "John", "age": 30})
        assert h1 != h2

    def test_empty_array_schema(self):
        h = compute_schema_hash({"items": []})
        assert h is not None
        assert len(h) == 16

    def test_none_payload(self):
        h = compute_schema_hash(None)
        assert h is not None
        assert len(h) == 16
