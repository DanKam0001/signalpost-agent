"""Reference reading of the batch input formats (R-1.3), independent of the product."""
import json

KEYS = ("organisation_number", "orgnr", "organization_number", "organisasjonsnummer")


def _from_obj(o):
    if isinstance(o, dict):
        for k in KEYS:
            if k in o and o[k] is not None:
                return str(o[k])
        return ""
    return str(o)


def read_batch(path):
    """Return the list of raw input identifiers (one per input row), normalised (whitespace removed)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    s = text.strip()
    rows = []
    if s.startswith("["):
        rows = [_from_obj(x) for x in json.loads(s)]
    else:
        for line in text.splitlines():
            if not line.strip():
                continue
            t = line.strip()
            if t.startswith("{"):
                rows.append(_from_obj(json.loads(t)))
            else:
                rows.append(t)
    return ["".join(r.split()) for r in rows]
