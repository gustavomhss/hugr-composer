#!/usr/bin/env bash
# Register N extra self-hosted runner instances on this mac so the parallel CI
# workflow (.github/workflows/ci-selfhosted.yml) can run its jobs concurrently.
#
# One existing runner (~/actions-runner) + 3 extras = 4 → the 6 CI jobs run in
# ~2 waves → ~max(job) instead of sum(steps).
#
# Usage:   scripts/ci/setup-runners.sh [count]      # default 3 extras
# Requires: gh CLI authenticated; the original ~/actions-runner present.
# No sudo needed (runners start with nohup ./run.sh). For boot-persistence,
# `sudo ./svc.sh install && sudo ./svc.sh start` in each dir instead.
set -euo pipefail

REPO="humangr-labs/HuGR-Arsenal"
COUNT="${1:-3}"
SRC="$HOME/actions-runner"
LABELS="self-hosted,macos,local"

[ -d "$SRC" ] || { echo "✗ original runner not found at $SRC"; exit 1; }
command -v gh >/dev/null || { echo "✗ gh CLI not found"; exit 1; }

echo "Minting a registration token for $REPO …"
TOKEN=$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" -q .token)
URL="https://github.com/${REPO}"

for i in $(seq 1 "$COUNT"); do
  DIR="$HOME/actions-runner-${i}"
  NAME="mac-runner-${i}"
  echo "── Setting up $NAME at $DIR"
  if [ -d "$DIR" ]; then
    echo "   exists; reconfiguring"
    ( cd "$DIR" && ./config.sh remove --token "$TOKEN" >/dev/null 2>&1 || true )
  else
    # Copy the runner binaries from the original install (same version).
    rsync -a --exclude '_work' --exclude '.runner' --exclude '.credentials*' "$SRC/" "$DIR/"
  fi
  ( cd "$DIR" \
      && ./config.sh --unattended --url "$URL" --token "$TOKEN" \
           --name "$NAME" --labels "$LABELS" --work _work --replace \
      && nohup ./run.sh > "run-${NAME}.log" 2>&1 & )
  echo "   started ($NAME) — log: $DIR/run-${NAME}.log"
done

echo
echo "✓ Requested $COUNT extra runners. Verify with:"
echo "    gh api repos/${REPO}/actions/runners -q '.runners[] | \"\\(.name): \\(.status)\"'"
echo "  (allow a few seconds for them to come online)"
