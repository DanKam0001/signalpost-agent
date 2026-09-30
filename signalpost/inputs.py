"""Batch input parsing: JSONL objects, a JSON array, or plain text (one number per line)."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

from .orgnr import normalise, validation_error

ORGNR_KEYS = ("organisation_number", "orgnr", "organization_number", "organisasjonsnummer")


@dataclass
class InputRow:
    index: int
    raw: str
    organisation_number: str
    error: str | None = None
    row: dict = field(default_factory=dict)

    @property
    def website_hint(self) -> str:
        value = self.row.get("website") or self.row.get("hjemmeside") or ""
        return value.strip() if isinstance(value, str) else ""


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8-sig")


def _row_from(item: object, index: int) -> InputRow:
    if isinstance(item, dict):
        raw = next((item[k] for k in ORGNR_KEYS if item.get(k) not in (None, "")), "")
        row = item
    else:
        raw, row = item, {}
    raw_text = str(raw).strip()
    number = normalise(raw_text)
    return InputRow(index=index, raw=raw_text, organisation_number=number,
                    error=validation_error(number), row=row)


def parse_items(text: str) -> list[object]:
    stripped = text.strip()
    if stripped.startswith("["):
        items = json.loads(stripped)
        if not isinstance(items, list):
            raise ValueError("JSON input must be an array")
        return items
    items: list[object] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            items.append(json.loads(line))
            continue
        value = line.split(",")[0].strip().strip('"')
        if value.lower() in ORGNR_KEYS:
            continue  # a CSV header line, not a company
        items.append(value)
    return items


def read_input(path: str | Path) -> list[InputRow]:
    items = parse_items(_read_text(Path(path)))
    return [_row_from(item, i) for i, item in enumerate(items)]
