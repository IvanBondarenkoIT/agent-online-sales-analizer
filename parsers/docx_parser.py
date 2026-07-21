"""Parse dialog conversations from DOCX files."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from docx import Document

DIALOG_MARKER_RE = re.compile(r"^#(\d+)$")


@dataclass
class Dialog:
    id: int
    section_index: int
    messages: list[str]

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def to_user_prompt(self) -> str:
        lines = [
            f"Диалог #{self.id} (секция {self.section_index}, {self.message_count} реплик):",
            "Определи роли (клиент/менеджер) по контексту и верни JSON по схеме.",
            "",
        ]
        for i, msg in enumerate(self.messages, start=1):
            lines.append(f"{i}. {msg}")
        return "\n".join(lines)


def _extract_paragraphs(docx_path: Path) -> list[str]:
    doc = Document(str(docx_path))
    lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)
    return lines


def _split_into_dialogs(lines: list[str]) -> list[Dialog]:
    dialogs: list[Dialog] = []
    current_id: int | None = None
    current_messages: list[str] = []
    section_index = 0

    def flush() -> None:
        nonlocal section_index, current_id, current_messages
        if current_id is not None and current_messages:
            section_index += 1
            dialogs.append(
                Dialog(
                    id=current_id,
                    section_index=section_index,
                    messages=current_messages,
                )
            )
        current_messages = []

    for line in lines:
        match = DIALOG_MARKER_RE.match(line)
        if match:
            flush()
            current_id = int(match.group(1))
            continue
        if current_id is not None:
            current_messages.append(line)

    flush()
    return dialogs


def detect_warnings(dialogs: list[Dialog]) -> list[str]:
    warnings: list[str] = []
    id_counts = Counter(d.id for d in dialogs)
    duplicates = [str(did) for did, count in id_counts.items() if count > 1]
    if duplicates:
        warnings.append(f"duplicate_marker_{','.join(duplicates)}")
    if not dialogs:
        warnings.append("no_dialogs_found")
    return warnings


def parse_docx(docx_path: Path) -> list[Dialog]:
    lines = _extract_paragraphs(docx_path)
    return _split_into_dialogs(lines)


def save_parsed_dialogs(dialogs: list[Dialog], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dialogs_count": len(dialogs),
        "warnings": detect_warnings(dialogs),
        "dialogs": [asdict(d) for d in dialogs],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
