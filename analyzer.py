"""Orchestrate dialog parsing, LLM analysis, aggregation, and report generation."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from config import Settings, load_prompt, setup_logging
from llm.base import LLMClient
from llm.factory import create_llm_client
from models.schemas import (
    AggregateStats,
    AvgScores,
    DialogAnalysis,
    DialogReport,
    Report41,
    ReportMeta,
    Scores,
    TopError,
)
from parsers.docx_parser import Dialog, detect_warnings, parse_docx, save_parsed_dialogs

logger = logging.getLogger("dimkava.analyzer")

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _save_partial_report(
    settings: Settings,
    dialogs: list[Dialog],
    warnings: list[str],
    reports: list[DialogReport],
) -> None:
    partial = Report41(
        meta=ReportMeta.create(
            source_file=settings.input_file.name,
            dialogs_count=len(dialogs),
            llm_provider=settings.llm_provider,
            model=settings.llm_model,
        ),
        aggregate=aggregate_results(reports),
        warnings=warnings,
        dialogs=reports,
    )
    path = settings.output_dir / "report_partial.json"
    path.write_text(
        json.dumps(partial.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_partial_reports(settings: Settings) -> dict[int, DialogReport]:
    path = settings.output_dir / "report_partial.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    reports: dict[int, DialogReport] = {}
    for item in data.get("dialogs", []):
        report = DialogReport.model_validate(item)
        reports[report.section_index] = report
    return reports


def extract_json(text: str) -> dict:
    text = text.strip()
    fence_match = JSON_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(text[start : end + 1])


def analyze_dialog(
    dialog: Dialog,
    llm: LLMClient,
    system_prompt: str,
    max_retries: int,
) -> DialogAnalysis:
    user_prompt = dialog.to_user_prompt()
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):
        try:
            logger.info(
                "Analyzing dialog #%s (section %s), attempt %s",
                dialog.id,
                dialog.section_index,
                attempt,
            )
            raw = llm.complete(system=system_prompt, user=user_prompt)
            data = extract_json(raw)
            analysis = DialogAnalysis.model_validate(data)
            logger.info(
                "Dialog #%s scores: needs_id=%s, cta=%s",
                dialog.id,
                analysis.scores.needs_id,
                analysis.scores.cta,
            )
            return analysis
        except (json.JSONDecodeError, ValidationError, ValueError, RuntimeError) as exc:
            last_error = exc
            logger.warning(
                "Dialog #%s attempt %s failed: %s",
                dialog.id,
                attempt,
                exc,
            )
            if attempt <= max_retries:
                time.sleep(1)

    raise RuntimeError(
        f"Failed to analyze dialog #{dialog.id} after {max_retries + 1} attempts: {last_error}"
    )


def aggregate_results(reports: list[DialogReport]) -> AggregateStats:
    if not reports:
        return AggregateStats(
            avg_scores=AvgScores(needs_id=0, cta=0),
            team_top_errors=[],
            low_score_dialogs=[],
        )

    total_needs = sum(r.analysis.scores.needs_id for r in reports)
    total_cta = sum(r.analysis.scores.cta for r in reports)
    count = len(reports)

    error_counter: Counter[str] = Counter()
    for report in reports:
        for error in report.analysis.errors_found:
            normalized = error.strip().lower()
            if normalized:
                error_counter[normalized] += 1

    top_errors: list[TopError] = []
    for error, err_count in error_counter.most_common(3):
        percent = round(err_count / count * 100, 1)
        top_errors.append(TopError(error=error, count=err_count, percent=percent))

    low_score_dialogs = sorted(
        {
            r.dialog_id
            for r in reports
            if r.analysis.scores.needs_id <= 2 or r.analysis.scores.cta <= 2
        }
    )

    return AggregateStats(
        avg_scores=AvgScores(
            needs_id=round(total_needs / count, 2),
            cta=round(total_cta / count, 2),
        ),
        team_top_errors=top_errors,
        low_score_dialogs=low_score_dialogs,
    )


def run_analysis(settings: Settings, *, resume: bool = False) -> Report41:
    settings.ensure_dirs()
    setup_logging(settings.logs_dir)

    logger.info("Starting analysis, provider=%s, resume=%s", settings.llm_provider, resume)
    settings.validate_for_analysis()

    dialogs = parse_docx(settings.input_file)
    warnings = detect_warnings(dialogs)
    logger.info("Parsed %s dialog sections from %s", len(dialogs), settings.input_file.name)

    existing = _load_partial_reports(settings) if resume else {}
    reports: list[DialogReport] = sorted(
        existing.values(), key=lambda r: r.section_index
    )
    done_sections = set(existing.keys())
    if done_sections:
        logger.info("Resuming: %s sections already in report_partial.json", len(done_sections))

    system_prompt = load_prompt("analyzer_system.txt")
    llm = create_llm_client(settings)

    processed_new = 0
    for i, dialog in enumerate(dialogs):
        if dialog.section_index in done_sections:
            logger.info(
                "Skipping dialog #%s (section %s) — already analyzed",
                dialog.id,
                dialog.section_index,
            )
            continue

        if processed_new > 0 and settings.request_delay_sec > 0:
            time.sleep(settings.request_delay_sec)

        analysis = analyze_dialog(
            dialog,
            llm,
            system_prompt,
            settings.max_retries,
        )
        reports.append(
            DialogReport(
                dialog_id=dialog.id,
                section_index=dialog.section_index,
                message_count=dialog.message_count,
                analysis=analysis,
            )
        )
        processed_new += 1
        reports.sort(key=lambda r: r.section_index)
        _save_partial_report(settings, dialogs, warnings, reports)

    report = Report41(
        meta=ReportMeta.create(
            source_file=settings.input_file.name,
            dialogs_count=len(dialogs),
            llm_provider=settings.llm_provider,
            model=settings.llm_model,
        ),
        aggregate=aggregate_results(reports),
        warnings=warnings,
        dialogs=reports,
    )

    output_path = settings.output_dir / "report_41.json"
    output_path.write_text(
        json.dumps(report.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Report saved to %s", output_path)
    return report


def run_parse_only(settings: Settings) -> Path:
    settings.ensure_dirs()
    setup_logging(settings.logs_dir)

    if not settings.input_file.exists():
        raise FileNotFoundError(f"Input file not found: {settings.input_file}")

    dialogs = parse_docx(settings.input_file)
    output_path = settings.output_dir / "parsed_dialogs.json"
    save_parsed_dialogs(dialogs, output_path)
    logger.info("Parsed %s dialogs -> %s", len(dialogs), output_path)
    return output_path
