"""Manual operator schedule: date ranges → operator name (Leeloo API has no sender id)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from config import PROJECT_ROOT

DEFAULT_SCHEDULE_PATH = PROJECT_ROOT / "config" / "operator_schedule.csv"


@dataclass(frozen=True)
class Shift:
    date_from: date
    date_to: date
    operator: str

    def contains(self, day: date) -> bool:
        return self.date_from <= day <= self.date_to

    def days(self) -> list[date]:
        out: list[date] = []
        cur = self.date_from
        while cur <= self.date_to:
            out.append(cur)
            cur += timedelta(days=1)
        return out


def default_schedule_path() -> Path:
    return DEFAULT_SCHEDULE_PATH


def load_schedule(path: Path | None = None) -> list[Shift]:
    schedule_path = path or DEFAULT_SCHEDULE_PATH
    if not schedule_path.exists():
        raise FileNotFoundError(f"Operator schedule not found: {schedule_path}")

    shifts: list[Shift] = []
    with schedule_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"date_from", "date_to", "operator"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"Schedule CSV must have columns date_from,date_to,operator "
                f"(got {reader.fieldnames!r})"
            )
        for i, row in enumerate(reader, start=2):
            raw_from = (row.get("date_from") or "").strip()
            raw_to = (row.get("date_to") or "").strip()
            op = (row.get("operator") or "").strip()
            if not raw_from and not raw_to and not op:
                continue
            if not raw_from or not raw_to or not op:
                raise ValueError(f"Schedule row {i}: empty date_from/date_to/operator")
            try:
                d_from = date.fromisoformat(raw_from)
                d_to = date.fromisoformat(raw_to)
            except ValueError as exc:
                raise ValueError(f"Schedule row {i}: invalid date ({exc})") from exc
            if d_from > d_to:
                raise ValueError(
                    f"Schedule row {i}: date_from {d_from} > date_to {d_to}"
                )
            shifts.append(Shift(date_from=d_from, date_to=d_to, operator=op))

    _validate_no_overlaps(shifts)
    return shifts


def _validate_no_overlaps(shifts: list[Shift]) -> None:
    ordered = sorted(shifts, key=lambda s: (s.date_from, s.date_to))
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.date_from <= prev.date_to:
            raise ValueError(
                f"Schedule overlap: {prev.operator} "
                f"{prev.date_from}–{prev.date_to} vs {cur.operator} "
                f"{cur.date_from}–{cur.date_to}"
            )


def operator_for(
    day: date,
    schedule: list[Shift] | None = None,
    *,
    path: Path | None = None,
) -> str | None:
    shifts = schedule if schedule is not None else load_schedule(path)
    for shift in shifts:
        if shift.contains(day):
            return shift.operator
    return None


def days_for_operator(
    operator: str,
    schedule: list[Shift] | None = None,
    *,
    path: Path | None = None,
) -> list[date]:
    shifts = schedule if schedule is not None else load_schedule(path)
    days: list[date] = []
    for shift in shifts:
        if shift.operator == operator:
            days.extend(shift.days())
    return sorted(set(days))


def days_by_operator(
    schedule: list[Shift],
    available_dates: list[date] | None = None,
) -> dict[str, list[date]]:
    available = set(available_dates) if available_dates is not None else None
    result: dict[str, list[date]] = {}
    for shift in schedule:
        for day in shift.days():
            if available is not None and day not in available:
                continue
            result.setdefault(shift.operator, []).append(day)
    for op in result:
        result[op] = sorted(set(result[op]))
    return result


def resolve_operator_label(
    day: date,
    *,
    meta_operator: str | None = None,
    schedule: list[Shift] | None = None,
    path: Path | None = None,
) -> str:
    if meta_operator and meta_operator.strip():
        return meta_operator.strip()
    try:
        shifts = schedule if schedule is not None else load_schedule(path)
    except FileNotFoundError:
        return "не указан"
    name = operator_for(day, shifts)
    return name if name else "не указан"


def format_date_list(days: list[date], *, max_show: int = 12) -> str:
    if not days:
        return "—"
    iso = [d.isoformat() for d in sorted(days)]
    if len(iso) <= max_show:
        return ", ".join(iso)
    head = ", ".join(iso[: max_show - 1])
    return f"{head}, … (+{len(iso) - (max_show - 1)} дн.)"
