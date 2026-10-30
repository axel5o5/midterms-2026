#!/bin/zsh
# Twice-daily midterm snapshot (launchd com.axel.midterms-snapshot). Saves the run and
# commits it: forecasters' daily numbers can't be fetched again later.
set -u
cd "$(dirname "$0")/.." || exit 1
UV="${UV:-$HOME/.local/bin/uv}"
"$UV" run --project . python -m midterms.snapshot || exit 1
git add data/snapshots
git diff --cached --quiet || git commit -q -m "snapshot $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q origin main || echo "push failed; commit is local"
