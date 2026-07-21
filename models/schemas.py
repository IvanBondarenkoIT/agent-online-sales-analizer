"""Pydantic schemas for dialog analysis and aggregated report."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Scores(BaseModel):
    needs_id: int = Field(ge=0, le=5)
    cta: int = Field(ge=0, le=5)


class DialogAnalysis(BaseModel):
    summary: str
    client_emotion: str
    errors_found: list[str]
    killer_phrase: str
    scores: Scores
    ideal_response_georgian: str

    @field_validator("errors_found")
    @classmethod
    def errors_not_empty(cls, v: list[str]) -> list[str]:
        return [e.strip() for e in v if e.strip()]


class DialogReport(BaseModel):
    dialog_id: int
    section_index: int
    message_count: int
    analysis: DialogAnalysis


class TopError(BaseModel):
    error: str
    count: int
    percent: float


class AvgScores(BaseModel):
    needs_id: float
    cta: float


class AggregateStats(BaseModel):
    avg_scores: AvgScores
    team_top_errors: list[TopError]
    low_score_dialogs: list[int]


class ReportMeta(BaseModel):
    source_file: str
    dialogs_count: int
    llm_provider: str
    model: str
    generated_at: str

    @classmethod
    def create(
        cls,
        source_file: str,
        dialogs_count: int,
        llm_provider: str,
        model: str,
    ) -> ReportMeta:
        return cls(
            source_file=source_file,
            dialogs_count=dialogs_count,
            llm_provider=llm_provider,
            model=model,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


class Report41(BaseModel):
    meta: ReportMeta
    aggregate: AggregateStats
    warnings: list[str]
    dialogs: list[DialogReport]

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
