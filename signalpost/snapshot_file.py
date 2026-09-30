"""Optional frozen registry snapshot (Brreg bulk download) used for identity anchoring.

Accepted formats: the Brreg bulk JSON (a JSON array of entities, optionally gzipped), JSONL, or
the Brreg bulk CSV whose dotted headers (e.g. `forretningsadresse.postnummer`) are expanded into
the API's nested shape. Only the organisation numbers of the current batch are kept in memory.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path

_CHUNK = 1 << 20


def _open_text(path: Path):
    raw = path.open("rb")
    head = raw.read(2)
    raw.seek(0)
    stream = gzip.GzipFile(fileobj=raw) if head == b"\x1f\x8b" else raw
    return io.TextIOWrapper(stream, encoding="utf-8-sig")


def _iter_json_array(fh):
    decoder = json.JSONDecoder(parse_float=Decimal)
    buf = fh.read(_CHUNK).lstrip()
    if not buf.startswith("["):
        raise ValueError("not a JSON array")
    buf = buf[1:]
    while True:
        buf = buf.lstrip().lstrip(",").lstrip()
        if buf.startswith("]"):
            return
        try:
            obj, end = decoder.raw_decode(buf)
        except ValueError:
            more = fh.read(_CHUNK)
            if not more:
                return
            buf += more
            continue
        yield obj
        buf = buf[end:]
        if len(buf) < _CHUNK // 2:
            buf += fh.read(_CHUNK)


def _nest(row: dict) -> dict:
    out: dict = {}
    for key, value in row.items():
        if value in (None, ""):
            continue
        parts = key.split(".")
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if parts[-1] == "adresse":
            value = [line for line in value.split("\n") if line]
        elif value in ("true", "false"):
            value = value == "true"
        elif parts[-1] == "antallAnsatte" and value.isdigit():
            value = int(value)
        node[parts[-1]] = value
    return out


class RegistrySnapshot:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._sha256: str | None = None
        self.records: dict[str, dict] = {}

    @property
    def sha256(self) -> str:
        if self._sha256 is None:
            digest = hashlib.sha256()
            with self.path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(_CHUNK), b""):
                    digest.update(chunk)
            self._sha256 = digest.hexdigest()
        return self._sha256

    @property
    def identity(self) -> dict:
        return {"file": self.path.name, "sha256": self.sha256,
                "modified": self.path.stat().st_mtime}

    def load(self, wanted: set[str]) -> int:
        with _open_text(self.path) as fh:
            first = fh.read(1)
            while first and first.isspace():
                first = fh.read(1)
        with _open_text(self.path) as fh:
            if first == "[":
                rows = _iter_json_array(fh)
            elif first == "{":
                rows = (json.loads(line, parse_float=Decimal) for line in fh if line.strip())
            else:
                rows = (_nest(r) for r in csv.DictReader(fh))
            for row in rows:
                number = str(row.get("organisasjonsnummer") or "")
                if number in wanted:
                    self.records[number] = row
        return len(self.records)

    def get(self, orgnr: str) -> dict | None:
        return self.records.get(orgnr)
