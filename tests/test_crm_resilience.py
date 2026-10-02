"""Tests for CRM analysis resilience (retries, partial, cached raw, skip, concurrency)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from crm_analysis import (
    CrmChannel,
    CrmMessage,
    _delete_crm_partial,
    _load_crm_partial,
    _save_crm_partial,
    analyze_crm_dialog,
    run_crm_analysis,
)
from crm_response_time import WorkSchedule
from models.crm_schemas import (
    CrmDialogAnalysis,
    CrmDialogReport,
    DialogResponseTime,
)

SAMPLE_LLM_JSON = {
    "summary": "test",
    "client_emotion": "neutral",
    "errors_found": [],
    "strengths_found": ["ok"],
    "killer_phrase": "hi",
    "scores": {
        "needs_id": 3,
        "objections_handled": 3,
        "value_presented": 3,
        "cta": 3,
        "deal_closed": 2,
    },
    "checklist": [{"criterion": "greeting_contact", "passed": True, "note": ""}],
    "ideal_response_georgian": "gamarjoba",
}


def _test_settings(**overrides):
    from config import Settings

    defaults = dict(
        project_root=Path("."),
        output_dir=Path("output"),
        logs_dir=Path("logs"),
        input_file=Path("x.docx"),
        llm_provider="cursor",
        llm_model="test",
        cursor_api_key="k",
        openrouter_api_key="",
        max_retries=1,
        request_delay_sec=0,
        crm_timezone="Asia/Tbilisi",
        crm_work_start="10:00",
        crm_work_end="18:00",
        crm_work_days="0,1,2,3,4",
        crm_sla_work_seconds=120,
        crm_sla_off_seconds=900,
        crm_llm_concurrency=1,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _sample_channel(cid: str = "ch1", name: str = "Alice") -> CrmChannel:
    msg = CrmMessage(
        "m1",
        "hello",
        "FRIEND_MESSAGE",
        None,
        cid,
        name,
        "FB",
    )
    return CrmChannel(cid, name, "FB", [msg])


def _sample_rt(cid: str = "ch1", name: str = "Alice") -> DialogResponseTime:
    return DialogResponseTime(channel_id=cid, person_name=name)


def _sample_report(cid: str = "ch1", name: str = "Alice") -> CrmDialogReport:
    return CrmDialogReport(
        channel_id=cid,
        person_name=name,
        platform="FB",
        message_count=1,
        analysis=CrmDialogAnalysis.model_validate(SAMPLE_LLM_JSON),
        response_time=_sample_rt(cid, name),
    )


def _write_jsonl(path: Path, channels: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for cid, name in channels:
        lines.append(
            json.dumps(
                {
                    "channel_id": cid,
                    "person_name": name,
                    "platform": "FB",
                    "message_id": f"m-{cid}",
                    "text": "hi",
                    "type": "FRIEND_MESSAGE",
                    "created_at": "2026-08-28T10:00:00+04:00",
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestAnalyzeCrmDialogRetries(unittest.TestCase):
    def test_retries_httpx_then_succeeds(self):
        llm = MagicMock()
        llm.complete.side_effect = [
            httpx.ReadTimeout("timeout"),
            json.dumps(SAMPLE_LLM_JSON),
        ]
        with patch("crm_analysis.time.sleep"):
            result = analyze_crm_dialog(
                _sample_channel(),
                _sample_rt(),
                date(2026, 8, 28),
                WorkSchedule(),
                llm,
                "system",
                max_retries=2,
            )
        self.assertEqual(result.summary, "test")
        self.assertEqual(llm.complete.call_count, 2)

    def test_httpx_exhausted_raises_runtime_error(self):
        llm = MagicMock()
        llm.complete.side_effect = httpx.RemoteProtocolError("disconnect")
        with patch("crm_analysis.time.sleep"):
            with self.assertRaises(RuntimeError):
                analyze_crm_dialog(
                    _sample_channel(),
                    _sample_rt(),
                    date(2026, 8, 28),
                    WorkSchedule(),
                    llm,
                    "system",
                    max_retries=1,
                )


class TestCrmPartialCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_and_load_partial_by_channel_id(self):
        settings = _test_settings(output_dir=self.output_dir, logs_dir=self.output_dir / "logs")
        target = date(2026, 8, 28)
        report = _sample_report()
        _save_crm_partial(settings, target, "/tmp/messages.jsonl", [report])
        loaded = _load_crm_partial(settings, target)
        self.assertIn("ch1", loaded)
        self.assertEqual(loaded["ch1"].person_name, "Alice")
        _delete_crm_partial(settings, target)
        self.assertEqual(_load_crm_partial(settings, target), {})


class TestRunCrmAnalysisCachedRaw(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output_dir = self.root / "output"
        self.output_dir.mkdir()
        self.raw_dir = self.output_dir / "crm_raw" / "2026-08-28" / "2026-08-28"
        self.jsonl_path = self.raw_dir / "messages.jsonl"
        _write_jsonl(self.jsonl_path, [("ch1", "Alice")])

    def tearDown(self):
        self.tmp.cleanup()

    @patch("crm_excel_export.export_crm_excel")
    @patch("crm_analysis.write_crm_report_md")
    @patch("crm_analysis.create_llm_client")
    @patch("crm_analysis.load_prompt", return_value="system")
    @patch("crm_analysis.fetch_calendar_day")
    def test_skips_fetch_when_cached_raw_exists(
        self,
        mock_fetch,
        _mock_prompt,
        mock_llm_factory,
        _mock_md,
        mock_excel,
    ):
        llm = MagicMock()
        llm.complete.return_value = json.dumps(SAMPLE_LLM_JSON)
        mock_llm_factory.return_value = llm
        mock_excel.return_value = {"daily": "d.xlsx", "master": "m.xlsx"}

        settings = _test_settings(
            project_root=self.root,
            output_dir=self.output_dir,
            logs_dir=self.output_dir / "logs",
            input_file=self.root / "x.docx",
        )
        with patch("crm_analysis.setup_logging"), patch.object(
            type(settings), "validate_llm_only", return_value=None
        ):
            report = run_crm_analysis(
                settings, target_date=date(2026, 8, 28), force=False
            )
        mock_fetch.assert_not_called()
        self.assertEqual(report.meta.dialogs_count, 1)
        partial = self.output_dir / "crm_partial_2026-08-28.json"
        self.assertFalse(partial.exists())


class TestRunCrmAnalysisSkipAndConcurrency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output_dir = self.root / "output"
        self.output_dir.mkdir()
        self.raw_dir = self.output_dir / "crm_raw" / "2026-08-28" / "2026-08-28"
        self.jsonl_path = self.raw_dir / "messages.jsonl"
        _write_jsonl(self.jsonl_path, [("ch1", "Alice"), ("ch2", "Bob")])

    def tearDown(self):
        self.tmp.cleanup()

    def _settings(self, **overrides):
        defaults = dict(
            project_root=self.root,
            output_dir=self.output_dir,
            logs_dir=self.output_dir / "logs",
            input_file=self.root / "x.docx",
        )
        defaults.update(overrides)
        return _test_settings(**defaults)

    @patch("crm_excel_export.export_crm_excel")
    @patch("crm_analysis.write_crm_report_md")
    @patch("crm_analysis.create_llm_client")
    @patch("crm_analysis.load_prompt", return_value="system")
    @patch("crm_analysis.fetch_calendar_day")
    def test_skips_llm_when_report_exists(
        self,
        mock_fetch,
        _mock_prompt,
        mock_llm_factory,
        _mock_md,
        mock_excel,
    ):
        # First run creates report
        llm = MagicMock()
        llm.complete.return_value = json.dumps(SAMPLE_LLM_JSON)
        mock_llm_factory.return_value = llm
        mock_excel.return_value = {"daily": "d.xlsx", "master": "m.xlsx"}
        settings = self._settings()
        with patch("crm_analysis.setup_logging"), patch.object(
            type(settings), "validate_llm_only", return_value=None
        ):
            first = run_crm_analysis(settings, target_date=date(2026, 8, 28), force=False)
        self.assertEqual(first.meta.dialogs_count, 2)
        self.assertEqual(llm.complete.call_count, 2)

        # Second run must skip LLM entirely
        llm.complete.reset_mock()
        with patch("crm_analysis.setup_logging"), patch.object(
            type(settings), "validate_llm_only", return_value=None
        ):
            second = run_crm_analysis(settings, target_date=date(2026, 8, 28), force=False)
        llm.complete.assert_not_called()
        mock_fetch.assert_not_called()
        self.assertEqual(second.meta.dialogs_count, 2)

    @patch("crm_excel_export.export_crm_excel")
    @patch("crm_analysis.write_crm_report_md")
    @patch("crm_analysis.create_llm_client")
    @patch("crm_analysis.load_prompt", return_value="system")
    @patch("crm_analysis.fetch_calendar_day")
    def test_force_recomputes_even_if_report_exists(
        self,
        mock_fetch,
        _mock_prompt,
        mock_llm_factory,
        _mock_md,
        mock_excel,
    ):
        llm = MagicMock()
        llm.complete.return_value = json.dumps(SAMPLE_LLM_JSON)
        mock_llm_factory.return_value = llm
        mock_excel.return_value = {"daily": "d.xlsx", "master": "m.xlsx"}
        mock_fetch.return_value = {"jsonl": str(self.jsonl_path)}
        settings = self._settings()
        with patch("crm_analysis.setup_logging"), patch.object(
            type(settings), "validate_llm_only", return_value=None
        ):
            run_crm_analysis(settings, target_date=date(2026, 8, 28), force=False)
            llm.complete.reset_mock()
            run_crm_analysis(settings, target_date=date(2026, 8, 28), force=True)
        self.assertEqual(llm.complete.call_count, 2)

    @patch("crm_excel_export.export_crm_excel")
    @patch("crm_analysis.write_crm_report_md")
    @patch("crm_analysis.create_llm_client")
    @patch("crm_analysis.load_prompt", return_value="system")
    @patch("crm_analysis.fetch_calendar_day")
    def test_concurrency_1_parity_with_two_dialogs(
        self,
        mock_fetch,
        _mock_prompt,
        mock_llm_factory,
        _mock_md,
        mock_excel,
    ):
        llm = MagicMock()
        llm.complete.return_value = json.dumps(SAMPLE_LLM_JSON)
        mock_llm_factory.return_value = llm
        mock_excel.return_value = {"daily": "d.xlsx", "master": "m.xlsx"}
        settings = self._settings(crm_llm_concurrency=1)
        with patch("crm_analysis.setup_logging"), patch.object(
            type(settings), "validate_llm_only", return_value=None
        ):
            report = run_crm_analysis(settings, target_date=date(2026, 8, 28), force=False)
        self.assertEqual(report.meta.dialogs_count, 2)
        self.assertEqual({d.channel_id for d in report.dialogs}, {"ch1", "ch2"})
        self.assertFalse((self.output_dir / "crm_partial_2026-08-28.json").exists())

    @patch("crm_excel_export.export_crm_excel")
    @patch("crm_analysis.write_crm_report_md")
    @patch("crm_analysis.create_llm_client")
    @patch("crm_analysis.load_prompt", return_value="system")
    @patch("crm_analysis.fetch_calendar_day")
    def test_concurrency_2_analyzes_all_dialogs(
        self,
        mock_fetch,
        _mock_prompt,
        mock_llm_factory,
        _mock_md,
        mock_excel,
    ):
        llm = MagicMock()
        llm.complete.return_value = json.dumps(SAMPLE_LLM_JSON)
        mock_llm_factory.return_value = llm
        mock_excel.return_value = {"daily": "d.xlsx", "master": "m.xlsx"}
        settings = self._settings(crm_llm_concurrency=2)
        with patch("crm_analysis.setup_logging"), patch.object(
            type(settings), "validate_llm_only", return_value=None
        ):
            report = run_crm_analysis(settings, target_date=date(2026, 8, 28), force=False)
        self.assertEqual(report.meta.dialogs_count, 2)
        self.assertEqual(llm.complete.call_count, 2)

    @patch("crm_excel_export.export_crm_excel")
    @patch("crm_analysis.write_crm_report_md")
    @patch("crm_analysis.create_llm_client")
    @patch("crm_analysis.load_prompt", return_value="system")
    @patch("crm_analysis.fetch_calendar_day")
    def test_soft_continue_keeps_partial_on_failure(
        self,
        mock_fetch,
        _mock_prompt,
        mock_llm_factory,
        _mock_md,
        mock_excel,
    ):
        llm = MagicMock()

        def _complete(system: str, user: str) -> str:
            if "Alice" in user:
                return json.dumps(SAMPLE_LLM_JSON)
            raise httpx.RemoteProtocolError("disconnect")

        llm.complete.side_effect = _complete
        mock_llm_factory.return_value = llm
        mock_excel.return_value = {"daily": "d.xlsx", "master": "m.xlsx"}
        settings = self._settings(max_retries=0)
        with patch("crm_analysis.setup_logging"), patch.object(
            type(settings), "validate_llm_only", return_value=None
        ), patch("crm_analysis.time.sleep"):
            report = run_crm_analysis(settings, target_date=date(2026, 8, 28), force=False)
        self.assertEqual(report.meta.dialogs_count, 1)
        self.assertEqual(report.dialogs[0].channel_id, "ch1")
        partial = self.output_dir / "crm_partial_2026-08-28.json"
        self.assertTrue(partial.exists())


if __name__ == "__main__":
    unittest.main()
