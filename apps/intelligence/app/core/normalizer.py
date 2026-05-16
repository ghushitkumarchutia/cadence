from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_ISO_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
)
_NUMERIC_ID_PATTERN = re.compile(r"^\d{6,}$")
_EMAIL_PATTERN = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")
_JWT_PATTERN = re.compile(r"^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$")
_PHONE_PATTERN = re.compile(r"^\+?\d[\d\s\-()]{7,}\d$")
_IPV4_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_IPV6_PATTERN = re.compile(r"^([0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}$")

_MASKED_UUID = "__UUID__"
_MASKED_TIMESTAMP = "__TIMESTAMP__"
_MASKED_NUMERIC_ID = "__NUMERIC_ID__"
_MASKED_EMAIL = "__EMAIL__"
_MASKED_JWT = "__JWT__"
_MASKED_PHONE = "__PHONE__"
_MASKED_IP = "__IP__"

_MAX_DEPTH = 10


def normalize_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return _normalize_value(payload, depth=0)


def compute_payload_hash(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return hashlib.sha256(b"null").hexdigest()[:16]

    normalized = normalize_payload(payload)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_schema_hash(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return hashlib.sha256(b"null").hexdigest()[:16]

    structure = _extract_structure(payload, depth=0)
    canonical = json.dumps(structure, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _normalize_value(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return value

    if value is None:
        return None

    if isinstance(value, str):
        return _mask_string(value)

    if isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            k: _normalize_value(v, depth + 1)
            for k, v in sorted(value.items())
        }

    if isinstance(value, list):
        return [_normalize_value(item, depth + 1) for item in value]

    return str(value)


def _mask_string(value: str) -> str:
    if _JWT_PATTERN.match(value):
        return _MASKED_JWT

    if _UUID_PATTERN.fullmatch(value):
        return _MASKED_UUID

    if _ISO_TIMESTAMP_PATTERN.match(value):
        return _MASKED_TIMESTAMP

    if _NUMERIC_ID_PATTERN.match(value):
        return _MASKED_NUMERIC_ID

    if _EMAIL_PATTERN.match(value):
        return _MASKED_EMAIL

    if _PHONE_PATTERN.match(value):
        return _MASKED_PHONE

    if _IPV4_PATTERN.match(value) or _IPV6_PATTERN.match(value):
        return _MASKED_IP

    return value


def _extract_structure(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return type(value).__name__

    if value is None:
        return "null"

    if isinstance(value, bool):
        return "boolean"

    if isinstance(value, (int, float)):
        return "number"

    if isinstance(value, str):
        return "string"

    if isinstance(value, dict):
        return {
            k: _extract_structure(v, depth + 1)
            for k, v in sorted(value.items())
        }

    if isinstance(value, list):
        if not value:
            return ["array_empty"]
        return [_extract_structure(value[0], depth + 1)]

    return type(value).__name__
