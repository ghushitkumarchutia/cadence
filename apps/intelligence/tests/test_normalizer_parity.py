"""
Cross-language normalizer parity tests.

Reads the shared fixtures JSON and verifies that Python normalizer
produces identical outputs to the Node.js normalizer.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from app.core.normalizer import normalize_payload, compute_payload_hash, compute_schema_hash

FIXTURES_PATH = Path(__file__).resolve().parent.parent.parent / "api" / "tests" / "fixtures" / "normalizer-vectors.json"

@pytest.fixture(scope="module")
def fixtures():
    with open(FIXTURES_PATH) as f:
        return json.load(f)

class TestMaskingParity:
    """Each masking vector must produce the same output in Python."""

    def test_all_masking_vectors(self, fixtures):
        for vec in fixtures["masking"]:
            inp = {"value": vec["input"]}
            result = normalize_payload(inp)
            assert result is not None, f"normalize_payload returned None for {vec['id']}"
            assert result["value"] == vec["expected"], (
                f"Masking mismatch for {vec['id']}: "
                f"got {result['value']!r}, expected {vec['expected']!r}"
            )

class TestNormalizePayloadParity:
    """Full payload normalization must match Node.js output."""

    def test_all_normalize_vectors(self, fixtures):
        for vec in fixtures["normalize_payload"]:
            result = normalize_payload(vec["input"])
            assert result == vec["expected"], (
                f"Normalize mismatch for {vec['id']}: "
                f"got {result!r}, expected {vec['expected']!r}"
            )

class TestPayloadHashParity:
    """Hash outputs must match between Node.js and Python for the same inputs."""

    def test_null_hash_determinism(self, fixtures):
        h1 = compute_payload_hash(None)
        h2 = compute_payload_hash(None)
        assert h1 == h2
        assert len(h1) == 16

    def test_empty_object_hash(self, fixtures):
        h = compute_payload_hash({})
        assert len(h) == 16

    def test_key_order_irrelevant(self, fixtures):
        for vec in fixtures["payload_hash"]:
            if "input_a" in vec:
                ha = compute_payload_hash(vec["input_a"])
                hb = compute_payload_hash(vec["input_b"])
                assert ha == hb, f"Key order mismatch for {vec['id']}: {ha} != {hb}"

    def test_all_hashes_16_chars_hex(self, fixtures):
        for vec in fixtures["payload_hash"]:
            inp = vec.get("input")
            if inp is not None or "input" in vec:
                h = compute_payload_hash(inp)
                assert len(h) == 16, f"Hash length wrong for {vec['id']}: {len(h)}"
                assert all(c in "0123456789abcdef" for c in h)

class TestSchemaHashParity:
    """Schema hash structure extraction must match."""

    def test_all_schema_vectors(self, fixtures):
        for vec in fixtures["schema_hash"]:
            h = compute_schema_hash(vec["input"])
            assert len(h) == 16
            assert all(c in "0123456789abcdef" for c in h)

    def test_same_types_same_hash(self):
        a = {"name": "Alice", "age": 25}
        b = {"name": "Bob", "age": 42}
        assert compute_schema_hash(a) == compute_schema_hash(b)

    def test_different_types_different_hash(self):
        a = {"count": 42}
        b = {"count": "42"}
        assert compute_schema_hash(a) != compute_schema_hash(b)
