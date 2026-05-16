from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class DominantType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"


class LatencyStats(BaseModel):
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    mean: float = 0.0
    std: float = 0.0


class ResponseSizeStats(BaseModel):
    mean: float = 0.0
    std: float = 0.0
    p95: float = 0.0


class ResponseLevelFeatures(BaseModel):
    latency: LatencyStats = Field(default_factory=LatencyStats)
    status_codes: dict[str, float] = Field(default_factory=dict)
    response_size: ResponseSizeStats = Field(default_factory=ResponseSizeStats)
    payload_entropy: float = 0.0
    schema_hash: str | None = None
    schema_version: str | None = None


class FieldFeatures(BaseModel):
    presence_rate: float = 0.0
    null_rate: float = 0.0
    type_consistency: float = 0.0
    dominant_type: DominantType = DominantType.NULL
    mean: float | None = None
    std: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p95: float | None = None
    p99: float | None = None
    min_val: float | None = None
    max_val: float | None = None
    mean_length: float | None = None
    std_length: float | None = None
    vocabulary_size: int | None = None
    vocabulary_entropy: float | None = None
    enum_values: list[str] | None = None
    enum_distribution: dict[str, float] | None = None


class FeatureVectorData(BaseModel):
    window_start: datetime
    window_end: datetime
    sample_count: int
    response_level: ResponseLevelFeatures = Field(default_factory=ResponseLevelFeatures)
    fields: dict[str, FieldFeatures] = Field(default_factory=dict)

    @field_validator("window_start", "window_end", mode="before")
    @classmethod
    def parse_datetime(cls, v: datetime | str) -> datetime:
        if isinstance(v, str):
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
