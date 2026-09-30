import gzip
import json

from signalpost.inputs import read_input
from signalpost.orgnr import is_valid, normalise, validation_error


def test_valid_and_invalid_numbers():
    assert is_valid("923609016")
    assert is_valid("810034882")
    assert "check digit" in validation_error("923609017")
    assert "9 digits" in validation_error("12345")
    assert "only digits" in validation_error("92360901X")


def test_normalise_common_formats():
    assert normalise(" 923 609 016 ") == "923609016"
    assert normalise("NO 923609016 MVA") == "923609016"
    assert normalise("923.609.016") == "923609016"


def test_universe_jsonl_rows(tmp_path):
    path = tmp_path / "in.jsonl"
    rows = [{"organisation_number": "810034882", "name": "SANDNES ELEKTRISKE AS", "website": ""},
            {"orgnr": "923 609 016", "website": "www.equinor.com"}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    parsed = read_input(path)
    assert [r.organisation_number for r in parsed] == ["810034882", "923609016"]
    assert parsed[1].website_hint == "www.equinor.com"
    assert all(r.error is None for r in parsed)


def test_json_array_text_and_gzip(tmp_path):
    arr = tmp_path / "in.json"
    arr.write_text(json.dumps(["923609016", {"organisasjonsnummer": "810034882"}]))
    assert [r.organisation_number for r in read_input(arr)] == ["923609016", "810034882"]
    txt = tmp_path / "in.txt"
    txt.write_text("organisation_number\n923609016\n\n  923 609 017 \n# comment\n")
    parsed = read_input(txt)
    assert [r.organisation_number for r in parsed] == ["923609016", "923609017"]
    assert parsed[1].error is not None
    gz = tmp_path / "in.jsonl.gz"
    gz.write_bytes(gzip.compress(b'{"organisation_number":"923609016"}\n'))
    assert read_input(gz)[0].organisation_number == "923609016"
