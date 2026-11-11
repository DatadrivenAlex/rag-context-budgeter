"""Offline whole-chunk context packing with exact rendered UTF-8 byte accounting."""

import math
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Chunk(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    source: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,200}$")
    text: str = Field(min_length=1, max_length=100_000)
    score: float = Field(ge=0, le=1)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Chunk text cannot be blank")
        return value

    @field_validator("score")
    @classmethod
    def finite_score(cls, value):
        if not math.isfinite(value):
            raise ValueError("Score must be finite")
        return value


class PackRequest(StrictModel):
    chunks: list[Chunk] = Field(max_length=1000)
    max_bytes: int = Field(ge=0, le=1_000_000)
    reserved_bytes: int = Field(default=0, ge=0)
    per_source: int = Field(default=2, ge=1, le=1000)

    @model_validator(mode="after")
    def valid_limits(self):
        if self.reserved_bytes > self.max_bytes:
            raise ValueError("Reserved bytes exceed total budget")
        ids = [chunk.id for chunk in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("Chunk IDs must be unique")
        return self


class Skipped(StrictModel):
    id: str
    reason: str


class PackResult(StrictModel):
    context: str
    used_bytes: int
    available_bytes: int
    selected_ids: list[str]
    citations: dict[str, str]
    skipped: list[Skipped]


def render(chunk: Chunk) -> str:
    return f"[{chunk.id}] source={chunk.source}\n{chunk.text.strip()}"


def fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def pack(request: PackRequest) -> PackResult:
    available = request.max_bytes - request.reserved_bytes
    parts = []
    selected = []
    citations = {}
    skipped = []
    seen = set()
    counts = {}
    used = 0
    # Ties use ID, never input order. Greedy whole chunks; not a knapsack optimizer.
    for chunk in sorted(request.chunks, key=lambda c: (-c.score, c.id)):
        key = fingerprint(chunk.text)
        if key in seen:
            skipped.append(Skipped(id=chunk.id, reason="duplicate_text"))
            continue
        if counts.get(chunk.source, 0) >= request.per_source:
            skipped.append(Skipped(id=chunk.id, reason="source_limit"))
            continue
        section = render(chunk)
        cost = len(section.encode("utf-8")) + (2 if parts else 0)
        if used + cost > available:
            skipped.append(Skipped(id=chunk.id, reason="over_budget"))
            continue
        parts.append(section)
        used += cost
        selected.append(chunk.id)
        citations[chunk.id] = chunk.source
        seen.add(key)
        counts[chunk.source] = counts.get(chunk.source, 0) + 1
    return PackResult(
        context="\n\n".join(parts),
        used_bytes=used,
        available_bytes=available,
        selected_ids=selected,
        citations=citations,
        skipped=skipped,
    )
