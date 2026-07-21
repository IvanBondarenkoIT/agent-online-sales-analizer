"""Pydantic schemas for CRM dialog analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CrmScores(BaseModel):
    needs_id: int = Field(ge=0, le=5)
    objections_handled: int = Field(ge=0, le=5)
    value_presented: int = Field(ge=0, le=5)
    cta: int = Field(ge=0, le=5)
    deal_closed: int = Field(ge=0, le=5)


class ChecklistItem(BaseModel):
    criterion: str
    passed: bool
    note: str = ""


class ResponseTimeStats(BaseModel):
    # Overall (wall-clock)
    avg_seconds: float | None = None
    median_seconds: float | None = None
    min_seconds: float | None = None
    max_seconds: float | None = None
    min_dialog: str | None = None
    max_dialog: str | None = None
    responses_count: int = 0
    over_15min: int = 0
    over_1hour: int = 0
    # Working hours (client wrote during shift)
    avg_work_seconds: float | None = None
    median_work_seconds: float | None = None
    min_work_seconds: float | None = None
    max_work_seconds: float | None = None
    responses_count_work: int = 0
    over_sla_work: int = 0
    # Off hours (client wrote outside shift / weekend)
    avg_off_seconds: float | None = None
    median_off_seconds: float | None = None
    min_off_seconds: float | None = None
    max_off_seconds: float | None = None
    responses_count_off: int = 0
    over_sla_off: int = 0


class DialogResponseTime(BaseModel):
    channel_id: str
    person_name: str
    avg_seconds: float | None = None
    min_seconds: float | None = None
    max_seconds: float | None = None
    responses_count: int = 0
    avg_work_seconds: float | None = None
    min_work_seconds: float | None = None
    max_work_seconds: float | None = None
    responses_count_work: int = 0
    over_sla_work: int = 0
    avg_off_seconds: float | None = None
    min_off_seconds: float | None = None
    max_off_seconds: float | None = None
    responses_count_off: int = 0
    over_sla_off: int = 0


class CrmDialogAnalysis(BaseModel):
    summary: str
    client_emotion: str
    errors_found: list[str]
    strengths_found: list[str]
    killer_phrase: str
    scores: CrmScores
    checklist: list[ChecklistItem]
    ideal_response_georgian: str
    response_speed_notes: str = ""

    @field_validator("errors_found", "strengths_found")
    @classmethod
    def strip_nonempty(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s.strip()]


class CrmDialogReport(BaseModel):
    channel_id: str
    person_name: str
    platform: str
    message_count: int
    analysis: CrmDialogAnalysis
    response_time: DialogResponseTime


class CrmReportMeta(BaseModel):
    source: str
    target_date: str
    dialogs_count: int
    messages_count: int
    llm_provider: str
    model: str
    generated_at: str
    report_type: str = "daily"
    date_from: str | None = None
    date_to: str | None = None
    days_in_period: int | None = None

    @classmethod
    def create(
        cls,
        source: str,
        target_date: str,
        dialogs_count: int,
        messages_count: int,
        llm_provider: str,
        model: str,
    ) -> CrmReportMeta:
        return cls(
            source=source,
            target_date=target_date,
            dialogs_count=dialogs_count,
            messages_count=messages_count,
            llm_provider=llm_provider,
            model=model,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


class CrmAggregateStats(BaseModel):
    avg_scores: dict[str, float]
    checklist_pass_rate: dict[str, float]
    top_errors: list[dict[str, Any]]
    top_strengths: list[dict[str, Any]]
    response_time: ResponseTimeStats


class CrmAnalysisReport(BaseModel):
    meta: CrmReportMeta
    aggregate: CrmAggregateStats
    dialogs: list[CrmDialogReport]
    daily_summaries: list[dict[str, Any]] = Field(default_factory=list)
    worst_dialogs: list[dict[str, Any]] = Field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
