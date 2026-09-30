#!/usr/bin/env bash
# Full verification of one commit. usage: run_all.sh COMMIT [SEED=73101]
# 1 acceptance (clean clone, empty venv, declared install, 100 random) 2 scenarios 3 differential 4 repo/docs/docker
# 5 UI 6 coverage table.  Web fixtures server is started for the website scenarios.
set -u
C=$1; SEED=${2:-73101}; HERE=$(cd "$(dirname "$0")" && pwd); TAG=${C:0:10}
WORK=/tmp/sp-accept-$TAG-$SEED-100
"$HERE/acceptance.sh" "$C" "$SEED" 100 "$WORK"
REPO=$WORK/repo
python3 "$HERE/webserve.py" > "$HERE/logs/webserve.out" 2>&1 & WS=$!
python3 "$HERE/scenarios.py" --repo "$REPO" --tag "$TAG"
kill $WS
python3 "$HERE/differential.py" --repo "$REPO" --tag "$TAG"
python3 "$HERE/repo_checks.py" --repo "$REPO" --tag "$TAG" --docker
"$HERE/.cache/vvenv/bin/python" "$HERE/ui_checks.py" --repo "$REPO" --tag "$TAG" --batch "$WORK/out/envelopes.jsonl"
python3 "$HERE/coverage.py" --tag "$TAG" --acceptance "$HERE/logs/acceptance-$TAG-seed$SEED-n100" | tee "$HERE/logs/$TAG/coverage.md"
