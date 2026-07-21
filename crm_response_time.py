"""Business-hours-aware response time calculation for CRM analysis."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from models.crm_schemas import DialogResponseTime, ResponseTimeStats

ResponseBucket = Literal["working", "off_hours"]

_TBILISI_OFFSET = timezone(timedelta(hours=4))


def _get_tz(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        return _TBILISI_OFFSET


@dataclass(frozen=True)
class WorkSchedule:
    timezone: str = "Asia/Tbilisi"
    work_start: time = time(10, 0)
    work_end: time = time(18, 0)
    work_weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})  # Mon-Fri
    sla_work_seconds: float = 120.0
    sla_off_seconds: float = 900.0

    @property
    def tz(self):
        return _get_tz(self.timezone)

    @classmethod
    def from_settings(cls, settings) -> WorkSchedule:
        start_h, start_m = _parse_hhmm(settings.crm_work_start)
        end_h, end_m = _parse_hhmm(settings.crm_work_end)
        days = frozenset(int(d.strip()) for d in settings.crm_work_days.split(",") if d.strip())
        return cls(
            timezone=settings.crm_timezone,
            work_start=time(start_h, start_m),
            work_end=time(end_h, end_m),
            work_weekdays=days,
            sla_work_seconds=float(settings.crm_sla_work_seconds),
            sla_off_seconds=float(settings.crm_sla_off_seconds),
        )


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def _to_local(dt: datetime, schedule: WorkSchedule) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(schedule.tz)


def is_work_moment(dt: datetime, schedule: WorkSchedule) -> bool:
    local = _to_local(dt, schedule)
    if local.weekday() not in schedule.work_weekdays:
        return False
    t = local.time()
    return schedule.work_start <= t < schedule.work_end


def _work_window_start(local_date: date, schedule: WorkSchedule) -> datetime:
    return datetime.combine(local_date, schedule.work_start, tzinfo=schedule.tz)


def _work_window_end(local_date: date, schedule: WorkSchedule) -> datetime:
    return datetime.combine(local_date, schedule.work_end, tzinfo=schedule.tz)


def _next_work_start(local_dt: datetime, schedule: WorkSchedule) -> datetime:
    """First work moment at or after local_dt."""
    local = local_dt if local_dt.tzinfo else local_dt.replace(tzinfo=schedule.tz)
    if is_work_moment(local, schedule):
        return local
    t = local.time()
    d = local.date()
    if local.weekday() in schedule.work_weekdays and t < schedule.work_start:
        return _work_window_start(d, schedule)
    d += timedelta(days=1)
    while d.weekday() not in schedule.work_weekdays:
        d += timedelta(days=1)
    return _work_window_start(d, schedule)


def working_seconds_between(
    client_ts: datetime,
    manager_ts: datetime,
    schedule: WorkSchedule,
) -> float:
    """Count seconds elapsed only during configured work windows."""
    if manager_ts < client_ts:
        return 0.0

    start = _next_work_start(_to_local(client_ts, schedule), schedule)
    end = _to_local(manager_ts, schedule)
    if end <= start:
        return 0.0

    total = 0.0
    cursor = start
    while cursor < end:
        day = cursor.date()
        if cursor.weekday() in schedule.work_weekdays:
            win_start = max(cursor, _work_window_start(day, schedule))
            win_end = min(end, _work_window_end(day, schedule))
            if win_end > win_start:
                total += (win_end - win_start).total_seconds()
        cursor = _work_window_start(day + timedelta(days=1), schedule)
        if cursor.weekday() not in schedule.work_weekdays:
            cursor = _next_work_start(cursor, schedule)
    return total


def classify_client_bucket(client_ts: datetime, schedule: WorkSchedule) -> ResponseBucket:
    return "working" if is_work_moment(client_ts, schedule) else "off_hours"


@dataclass
class ResponsePairMetrics:
    wall_seconds: float
    work_seconds: float
    bucket: ResponseBucket


def stats_from_deltas(
    deltas: list[float],
    *,
    sla_seconds: float,
    over_15min_field: bool = True,
) -> dict:
    if not deltas:
        return {
            "avg_seconds": None,
            "median_seconds": None,
            "min_seconds": None,
            "max_seconds": None,
            "responses_count": 0,
            "over_sla": 0,
            "over_15min": 0,
            "over_1hour": 0,
        }
    return {
        "avg_seconds": round(statistics.mean(deltas), 1),
        "median_seconds": round(statistics.median(deltas), 1),
        "min_seconds": round(min(deltas), 1),
        "max_seconds": round(max(deltas), 1),
        "responses_count": len(deltas),
        "over_sla": sum(1 for d in deltas if d > sla_seconds),
        "over_15min": sum(1 for d in deltas if d > 900) if over_15min_field else 0,
        "over_1hour": sum(1 for d in deltas if d > 3600),
    }


def build_response_time_stats(
    pairs: list[ResponsePairMetrics],
    schedule: WorkSchedule,
    person_names: dict[int, str] | None = None,
) -> tuple[ResponseTimeStats, list[float], list[float], list[float]]:
    """Build combined stats with overall / working / off_hours blocks."""
    overall = [p.wall_seconds for p in pairs]
    work = [p.work_seconds for p in pairs if p.bucket == "working"]
    off_wall = [p.wall_seconds for p in pairs if p.bucket == "off_hours"]

    o = stats_from_deltas(overall, sla_seconds=schedule.sla_off_seconds)
    w = stats_from_deltas(work, sla_seconds=schedule.sla_work_seconds, over_15min_field=False)
    off = stats_from_deltas(off_wall, sla_seconds=schedule.sla_off_seconds, over_15min_field=False)

    min_dialog = max_dialog = None
    if overall:
        min_i = min(range(len(overall)), key=lambda i: overall[i])
        max_i = max(range(len(overall)), key=lambda i: overall[i])
        if person_names:
            min_dialog = person_names.get(min_i)
            max_dialog = person_names.get(max_i)

    stats = ResponseTimeStats(
        avg_seconds=o["avg_seconds"],
        median_seconds=o["median_seconds"],
        min_seconds=o["min_seconds"],
        max_seconds=o["max_seconds"],
        min_dialog=min_dialog,
        max_dialog=max_dialog,
        responses_count=o["responses_count"],
        over_15min=o["over_15min"],
        over_1hour=o["over_1hour"],
        avg_work_seconds=w["avg_seconds"],
        median_work_seconds=w["median_seconds"],
        min_work_seconds=w["min_seconds"],
        max_work_seconds=w["max_seconds"],
        responses_count_work=w["responses_count"],
        over_sla_work=w["over_sla"],
        avg_off_seconds=off["avg_seconds"],
        median_off_seconds=off["median_seconds"],
        min_off_seconds=off["min_seconds"],
        max_off_seconds=off["max_seconds"],
        responses_count_off=off["responses_count"],
        over_sla_off=off["over_sla"],
    )
    return stats, overall, work, off_wall


def enrich_dialog_response_time(
    rt: DialogResponseTime,
    pairs: list[ResponsePairMetrics],
    schedule: WorkSchedule,
) -> DialogResponseTime:
    overall = [p.wall_seconds for p in pairs]
    work = [p.work_seconds for p in pairs if p.bucket == "working"]
    off_wall = [p.wall_seconds for p in pairs if p.bucket == "off_hours"]

    if overall:
        rt.avg_seconds = round(statistics.mean(overall), 1)
        rt.min_seconds = round(min(overall), 1)
        rt.max_seconds = round(max(overall), 1)
    rt.responses_count = len(overall)

    if work:
        rt.avg_work_seconds = round(statistics.mean(work), 1)
        rt.min_work_seconds = round(min(work), 1)
        rt.max_work_seconds = round(max(work), 1)
        rt.responses_count_work = len(work)
        rt.over_sla_work = sum(1 for d in work if d > schedule.sla_work_seconds)

    if off_wall:
        rt.avg_off_seconds = round(statistics.mean(off_wall), 1)
        rt.min_off_seconds = round(min(off_wall), 1)
        rt.max_off_seconds = round(max(off_wall), 1)
        rt.responses_count_off = len(off_wall)
        rt.over_sla_off = sum(1 for d in off_wall if d > schedule.sla_off_seconds)

    return rt
