"""Unit tests for operator-window compare (no LLM)."""

from __future__ import annotations

import unittest
from datetime import date

from crm_operator_compare import (
    MetricDelta,
    SCORE_DELTA_THRESHOLD,
    build_compare_metrics,
    classify_quality_findings,
    compare_operator_windows,
)
from models.crm_schemas import (
    CrmAggregateStats,
    CrmAnalysisReport,
    CrmReportMeta,
    ResponseTimeStats,
)


def _agg(
    *,
    scores: dict | None = None,
    checklist: dict | None = None,
    sla_work_over: int = 0,
    sla_work_n: int = 10,
    sla_off_over: int = 0,
    sla_off_n: int = 10,
    phone_rate: float = 0.0,
    errors: list | None = None,
    strengths: list | None = None,
) -> CrmAggregateStats:
    return CrmAggregateStats(
        avg_scores=scores or {
            "needs_id": 1.0,
            "objections_handled": 2.0,
            "value_presented": 2.0,
            "cta": 1.0,
            "deal_closed": 0.5,
        },
        checklist_pass_rate=checklist or {"concrete_cta": 40.0, "needs_identified": 50.0},
        top_errors=errors or [],
        top_strengths=strengths or [],
        response_time=ResponseTimeStats(
            over_sla_work=sla_work_over,
            responses_count_work=sla_work_n,
            over_sla_off=sla_off_over,
            responses_count_off=sla_off_n,
        ),
        phone_attempts_total=0,
        phone_successes_total=0,
        phone_success_rate=phone_rate,
    )


def _report(agg: CrmAggregateStats, *, dialogs: int, days: int, d_from: str, d_to: str) -> CrmAnalysisReport:
    meta = CrmReportMeta(
        source="test",
        target_date=f"{d_from}_{d_to}",
        dialogs_count=dialogs,
        messages_count=dialogs * 10,
        llm_provider="mock",
        model="mock",
        generated_at="2026-09-21T00:00:00+00:00",
        report_type="operator_window",
        date_from=d_from,
        date_to=d_to,
        days_in_period=days,
    )
    return CrmAnalysisReport(meta=meta, aggregate=agg, dialogs=[])


class TestOperatorCompareRules(unittest.TestCase):
    def test_score_plus_and_minus_thresholds(self):
        a = _report(_agg(scores={
            "needs_id": 1.50,
            "objections_handled": 2.00,
            "value_presented": 2.00,
            "cta": 1.00,
            "deal_closed": 0.50,
        }), dialogs=20, days=14, d_from="2026-09-05", d_to="2026-09-18")
        b = _report(_agg(scores={
            "needs_id": 1.70,
            "objections_handled": 2.00,
            "value_presented": 2.00,
            "cta": 0.80,
            "deal_closed": 0.50,
        }), dialogs=10, days=2, d_from="2026-09-19", d_to="2026-09-20")
        metrics = build_compare_metrics(a, b)
        pluses, minuses = classify_quality_findings(
            metrics, a_agg=a.aggregate, b_agg=b.aggregate, a_name="A", b_name="B"
        )
        self.assertTrue(any("потребност" in p.lower() or "Needs" in p or "потребн" in p for p in pluses) or any("Выявление" in p for p in pluses))
        self.assertTrue(any("CTA" in m for m in minuses))
        self.assertGreaterEqual(SCORE_DELTA_THRESHOLD, 0.15)

    def test_dialogs_per_day_not_quality(self):
        a = _report(_agg(), dialogs=140, days=14, d_from="2026-09-05", d_to="2026-09-18")
        b = _report(_agg(), dialogs=6, days=2, d_from="2026-09-19", d_to="2026-09-20")
        metrics = build_compare_metrics(a, b)
        vol = next(m for m in metrics if m.key == "dialogs_per_day")
        self.assertFalse(vol.quality)
        pluses, minuses = classify_quality_findings(
            metrics, a_agg=a.aggregate, b_agg=b.aggregate, a_name="A", b_name="B"
        )
        blob = " ".join(pluses + minuses)
        self.assertNotIn("Диалогов в день", blob)

    def test_qualitative_unique_error_is_minus(self):
        a = _report(_agg(errors=[{"error": "нет cta", "count": 1, "percent": 5.0}]), dialogs=20, days=14, d_from="2026-09-05", d_to="2026-09-18")
        b = _report(_agg(errors=[{"error": "нет cta", "count": 4, "percent": 40.0}]), dialogs=10, days=2, d_from="2026-09-19", d_to="2026-09-20")
        metrics: list[MetricDelta] = []
        pluses, minuses = classify_quality_findings(
            metrics, a_agg=a.aggregate, b_agg=b.aggregate, a_name="Основной", b_name="Замена"
        )
        self.assertTrue(any("нет cta" in m for m in minuses))
        self.assertFalse(any("нет cta" in p for p in pluses))

    def test_weekend_caveat_present(self):
        a = _report(_agg(), dialogs=20, days=14, d_from="2026-09-05", d_to="2026-09-18")
        b = _report(_agg(), dialogs=10, days=2, d_from="2026-09-19", d_to="2026-09-20")
        result = compare_operator_windows(
            a, b,
            a_name="Основной",
            b_name="Замена",
            a_from=date(2026, 9, 5),
            a_to=date(2026, 9, 18),
            b_from=date(2026, 9, 19),
            b_to=date(2026, 9, 20),
        )
        self.assertTrue(any("выходн" in c.lower() for c in result.caveats))


if __name__ == "__main__":
    unittest.main()
