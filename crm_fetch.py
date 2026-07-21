"""Fetch chat transcripts from Leeloo.ai CRM via lilu_chats exporter."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ANALYZER_ROOT = Path(__file__).resolve().parent
LILU_CHATS_ROOT = ANALYZER_ROOT.parent.parent / "lilu_chats"

load_dotenv(ANALYZER_ROOT / ".env")

_JSONL_RE = re.compile(r"JSONL:\s+(.+)", re.IGNORECASE)
_MD_RE = re.compile(r"Markdown:\s+(.+)", re.IGNORECASE)
_MANIFEST_RE = re.compile(r"Manifest:\s+(.+)", re.IGNORECASE)
_DIALOGS_RE = re.compile(r"Диалогов:\s+(\d+)", re.IGNORECASE)
_MESSAGES_RE = re.compile(r"Сообщений:\s+(\d+)", re.IGNORECASE)
_DISCOVERY_RE = re.compile(r"Discovery:\s+(\d+)", re.IGNORECASE)


def fetch_calendar_day(
    day: date,
    mode: str = "full_history",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Export chats active on a calendar day (full_history or period_messages)."""
    if not LILU_CHATS_ROOT.is_dir():
        raise FileNotFoundError(
            f"lilu_chats not found at {LILU_CHATS_ROOT}. "
            "Expected: D:\\CursorProjects\\lilu_chats"
        )

    out = output_dir or (ANALYZER_ROOT / "output" / "crm_raw" / day.isoformat())
    out.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "scripts.export_chats",
        "--date",
        day.isoformat(),
        "--mode",
        mode,
        "--output-dir",
        str(out),
    ]

    completed = subprocess.run(
        cmd,
        cwd=str(LILU_CHATS_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise RuntimeError(
            "CRM export failed "
            f"(exit {completed.returncode}).\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )

    combined = stdout + "\n" + stderr
    jsonl = _match_path(_JSONL_RE, combined, out)
    markdown = _match_path(_MD_RE, combined, out)
    manifest = _match_path(_MANIFEST_RE, combined, out)

    if not jsonl:
        jsonl_files = sorted(out.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not jsonl_files:
            jsonl_files = sorted(out.glob("chats_*.jsonl"), key=lambda p: p.stat().st_mtime)
        jsonl = str(jsonl_files[-1]) if jsonl_files else None
    if not markdown:
        md_files = sorted(out.glob("*.md"), key=lambda p: p.stat().st_mtime)
        if not md_files:
            md_files = sorted(out.glob("chats_*.md"), key=lambda p: p.stat().st_mtime)
        markdown = str(md_files[-1]) if md_files else None
    if not manifest:
        manifest_files = sorted(out.glob("*manifest.json"), key=lambda p: p.stat().st_mtime)
        manifest = str(manifest_files[-1]) if manifest_files else None

    return {
        "date": day.isoformat(),
        "mode": mode,
        "channels": _match_int(_DIALOGS_RE, combined),
        "messages": _match_int(_MESSAGES_RE, combined),
        "discovery_count": _match_int(_DISCOVERY_RE, combined),
        "jsonl": jsonl,
        "markdown": markdown,
        "manifest": manifest,
        "stdout": stdout.strip(),
    }


def fetch_last_n_days(days: int = 7, output_dir: Path | None = None) -> dict[str, Any]:
    """
    Download Messenger chats for the last N days.

    Runs lilu_chats exporter in a subprocess to avoid package name clashes
    (this project also has config.py and models/).
    """
    if days < 1:
        raise ValueError("days must be >= 1")

    if not LILU_CHATS_ROOT.is_dir():
        raise FileNotFoundError(
            f"lilu_chats not found at {LILU_CHATS_ROOT}. "
            "Expected: D:\\CursorProjects\\lilu_chats"
        )

    out = output_dir or (ANALYZER_ROOT / "output" / "crm_raw")
    out.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "scripts.export_chats",
        "--hours",
        str(days * 24),
        "--mode",
        "period_messages",
        "--output-dir",
        str(out),
    ]

    completed = subprocess.run(
        cmd,
        cwd=str(LILU_CHATS_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise RuntimeError(
            "CRM export failed "
            f"(exit {completed.returncode}).\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )

    combined = stdout + "\n" + stderr
    jsonl = _match_path(_JSONL_RE, combined, out)
    markdown = _match_path(_MD_RE, combined, out)
    manifest = _match_path(_MANIFEST_RE, combined, out)

    if not jsonl:
        jsonl_files = sorted(out.glob("chats_*.jsonl"), key=lambda p: p.stat().st_mtime)
        jsonl = str(jsonl_files[-1]) if jsonl_files else None
    if not markdown:
        md_files = sorted(out.glob("chats_*.md"), key=lambda p: p.stat().st_mtime)
        markdown = str(md_files[-1]) if md_files else None
    if not manifest:
        manifest_files = sorted(out.glob("chats_*_manifest.json"), key=lambda p: p.stat().st_mtime)
        manifest = str(manifest_files[-1]) if manifest_files else None

    return {
        "days": days,
        "channels": _match_int(_DIALOGS_RE, combined),
        "messages": _match_int(_MESSAGES_RE, combined),
        "discovery_count": _match_int(_DISCOVERY_RE, combined),
        "jsonl": jsonl,
        "markdown": markdown,
        "manifest": manifest,
        "stdout": stdout.strip(),
    }


def _match_path(pattern: re.Pattern[str], text: str, base: Path) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    path = Path(match.group(1).strip())
    return str(path if path.is_absolute() else base / path)


def _match_int(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text)
    return int(match.group(1)) if match else 0
