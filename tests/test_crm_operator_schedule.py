"""Tests for operator schedule CSV and compare-by-schedule day counts."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from crm_operator_schedule import (
    days_by_operator,
    days_for_operator,
    load_schedule,
    operator_for,
    resolve_operator_label,
)
from models.crm_schemas import (
    CrmAggregateStats,
    CrmAnalysisReport,
    CrmReportMeta,
    ResponseTimeStats,
)


def _write_csv(path: Path, rows: list[str]) -> None:
    path.write_text(
        "date_from,date_to,operator\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


class TestOperatorSchedule(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "schedule.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_and_operator_for(self) -> None:
        _write_csv(
            self.path,
            [
                "2026-09-05,2026-09-18,Основной",
                "2026-09-19,2026-09-20,Замена",
                "2026-09-21,2026-09-24,Основной",
            ],
        )
        shifts = load_schedule(self.path)
        self.assertEqual(len(shifts), 3)
        self.assertEqual(operator_for(date(2026, 9, 18), shifts), "Основной")
        self.assertEqual(operator_for(date(2026, 9, 19), shifts), "Замена")
        self.assertEqual(operator_for(date(2026, 9, 22), shifts), "Основной")
        self.assertIsNone(operator_for(date(2026, 10, 2), shifts))

    def test_overlap_raises(self) -> None:
        _write_csv(
            self.path,
            [
                "2026-09-01,2026-09-10,A",
                "2026-09-10,2026-09-12,B",
            ],
        )
        with self.assertRaises(ValueError) as ctx:
            load_schedule(self.path)
        self.assertIn("overlap", str(ctx.exception).lower())

    def test_from_after_to_raises(self) -> None:
        _write_csv(self.path, ["2026-09-10,2026-09-01,A"])
        with self.assertRaises(ValueError):
            load_schedule(self.path)

    def test_days_by_operator_with_available(self) -> None:
        _write_csv(
            self.path,
            [
                "2026-09-05,2026-09-18,Основной",
                "2026-09-19,2026-09-20,Замена",
                "2026-09-21,2026-09-24,Основной",
            ],
        )
        shifts = load_schedule(self.path)
        available = [
            date(2026, 9, 17),
            date(2026, 9, 18),
            date(2026, 9, 19),
            date(2026, 9, 21),
            date(2026, 9, 22),
        ]
        by_op = days_by_operator(shifts, available)
        self.assertEqual(
            by_op["Основной"],
            [date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22)],
        )
        self.assertEqual(by_op["Замена"], [date(2026, 9, 19)])

    def test_days_for_operator_noncontiguous(self) -> None:
        _write_csv(
            self.path,
            [
                "2026-09-05,2026-09-06,Основной",
                "2026-09-19,2026-09-20,Замена",
                "2026-09-21,2026-09-22,Основной",
            ],
        )
        days = days_for_operator("Основной", load_schedule(self.path))
        self.assertEqual(
            days,
            [
                date(2026, 9, 5),
                date(2026, 9, 6),
                date(2026, 9, 21),
                date(2026, 9, 22),
            ],
        )

    def test_resolve_prefers_meta(self) -> None:
        _write_csv(self.path, ["2026-09-05,2026-09-06,Основной"])
        label = resolve_operator_label(
            date(2026, 9, 5),
            meta_operator="Из meta",
            path=self.path,
        )
        self.assertEqual(label, "Из meta")
        self.assertEqual(
            resolve_operator_label(date(2026, 10, 2), path=self.path),
            "не указан",
        )


def _empty_agg() -> CrmAggregateStats:
    return CrmAggregateStats(
        avg_scores={
            "needs_id": 1.0,
            "objections_handled": 2.0,
            "value_presented": 2.0,
            "cta": 1.0,
            "deal_closed": 0.5,
        },
        checklist_pass_rate={},
        top_errors=[],
        top_strengths=[],
        response_time=ResponseTimeStats(),
    )


def _daily(target: str, dialogs: int = 10) -> CrmAnalysisReport:
    return CrmAnalysisReport(
        meta=CrmReportMeta.create(
            source="t",
            target_date=target,
            dialogs_count=dialogs,
            messages_count=dialogs * 5,
            llm_provider="mock",
            model="m",
            operator="Основной",
        ),
        aggregate=_empty_agg(),
        dialogs=[],
    )


class TestCompareByScheduleDays(unittest.TestCase):
    def test_load_days_sets_days_in_period_to_report_count(self) -> None:
        from crm_operator_compare import _load_days
        from config import Settings

        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            out = root / "output"
            out.mkdir()
            # Non-contiguous: 05,06 then 21,22 (4 days, calendar span has gap)
            import json

            for d, n in [
                ("2026-09-05", 10),
                ("2026-09-06", 10),
                ("2026-09-21", 10),
                ("2026-09-22", 10),
            ]:
                p = out / f"crm_report_{d}.json"
                p.write_text(
                    json.dumps(_daily(d, n).to_json_dict(), ensure_ascii=False),
                    encoding="utf-8",
                )

            settings = Settings(
                project_root=root,
                output_dir=out,
                logs_dir=out / "logs",
                input_file=root / "x.docx",
                llm_provider="mock",
                llm_model="m",
                cursor_api_key="",
                openrouter_api_key="",
                max_retries=0,
                request_delay_sec=0,
                crm_timezone="Asia/Tbilisi",
                crm_work_start="10:00",
                crm_work_end="18:00",
                crm_work_days="0,1,2,3,4",
                crm_sla_work_seconds=120,
                crm_sla_off_seconds=900,
                crm_llm_concurrency=1,
            )
            dates = [
                date(2026, 9, 5),
                date(2026, 9, 6),
                date(2026, 9, 21),
                date(2026, 9, 22),
            ]
            with patch("crm_batch._collect_period_pairs", return_value=[]):
                report = _load_days(settings, dates)
            # Non-contiguous: 4 reports across a 18-day calendar span → days_in_period=4
            self.assertEqual(report.meta.days_in_period, 4)
            summed = sum(int(s["dialogs_count"]) for s in report.daily_summaries)
            self.assertEqual(summed, 40)
            self.assertEqual(len(report.daily_summaries), 4)
            per_day = summed / (report.meta.days_in_period or 1)
            self.assertEqual(per_day, 10.0)
        finally:
            tmp.cleanup()

    def test_filter_operator_dates_since_and_last(self) -> None:
        from crm_operator_compare import _filter_operator_dates

        days = [
            date(2026, 9, 5),
            date(2026, 9, 10),
            date(2026, 9, 15),
            date(2026, 9, 18),
            date(2026, 9, 21),
        ]
        filtered = _filter_operator_dates(days, since=date(2026, 9, 10), last_days=2)
        self.assertEqual(filtered, [date(2026, 9, 18), date(2026, 9, 21)])


if __name__ == "__main__":
    unittest.main()
