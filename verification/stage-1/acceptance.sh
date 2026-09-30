#!/usr/bin/env bash
# R-1.58 official procedure: clean clone at COMMIT into a NEW folder, EMPTY venv, only the declared install
# step, then the single run command on COUNT random universe companies (seed SEED). Then all envelope checks.
# usage: acceptance.sh COMMIT [SEED=73101] [COUNT=100] [WORK=/tmp/sp-accept-<commit>-<seed>]
set -u
# The sandbox system python3.14 has no ensurepip, so a clean uv-managed CPython 3.12 is put first on PATH as
# `python3` (a stand-in for a normal machine). The declared install step then runs verbatim.
export PATH="$(cd "$(dirname "$0")" && pwd)/.cache/pyshim:$PATH"
COMMIT=$1; SEED=${2:-73101}; COUNT=${3:-100}
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd)
WORK=${4:-/tmp/sp-accept-${COMMIT:0:10}-$SEED-$COUNT}
LOG=$HERE/logs/acceptance-${COMMIT:0:10}-seed$SEED-n$COUNT; mkdir -p "$LOG"
rm -rf "$WORK"; mkdir -p "$WORK"
exec > >(tee "$LOG/acceptance.log") 2>&1
echo "== commit $COMMIT seed $SEED count $COUNT work $WORK  $(date -u +%FT%TZ)"
git clone -q "$REPO" "$WORK/repo" && cd "$WORK/repo" && git checkout -q "$COMMIT" || { echo "FAIL clone/checkout"; exit 2; }
echo "HEAD $(git rev-parse HEAD)"
python3 -m venv .venv || { echo "FAIL venv"; exit 2; }
echo "venv packages before install: $(.venv/bin/pip list --format=freeze 2>/dev/null | wc -l) (pip itself only expected)"
T0=$(date +%s)
bash -c 'python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt' || { echo "FAIL install"; exit 2; }
echo "install ok in $(( $(date +%s)-T0 ))s; pinned: $(grep -cE '==' requirements.txt)/$(grep -cvE '^\s*(#|$)' requirements.txt) lines"
python3 "$HERE/sample.py" --count "$COUNT" --seed "$SEED" --out "$WORK/batch.jsonl"
env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u BRAVE_API_KEY python3 "$HERE/lib/timed.py" "$LOG/time.json" -- \
  .venv/bin/python -m signalpost run --input "$WORK/batch.jsonl" --output "$WORK/out/envelopes.jsonl" --report "$WORK/out/report.json"
RC=$?
echo "run exit code: $RC  timing: $(cat "$LOG/time.json")"
echo "inputs: $(wc -l < "$WORK/batch.jsonl")  envelopes: $(grep -c . "$WORK/out/envelopes.jsonl" 2>/dev/null)"
cp "$WORK/batch.jsonl" "$LOG/"; cp "$WORK/out/report.json" "$LOG/" 2>/dev/null; cp "$WORK/out/envelopes.jsonl" "$LOG/" 2>/dev/null
python3 "$HERE/check_envelopes.py" --input "$WORK/batch.jsonl" --output "$WORK/out/envelopes.jsonl" --report "$WORK/out/report.json" --oracle --out "$LOG/checks.json"; CRC=$?
python3 "$HERE/check_evidence.py" --output "$WORK/out/envelopes.jsonl" --sample 250 --out "$LOG/evidence.json"; ERC=$?
echo "== RESULT run_rc=$RC checks_rc=$CRC evidence_rc=$ERC"
[ $RC -eq 0 ] && [ $CRC -eq 0 ] && [ $ERC -eq 0 ]
