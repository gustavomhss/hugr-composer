# Parallel CI runners

CI runs as parallel **jobs** (lint / unit / composition / integration / auth-mcp /
postgres-behavior) so the 12-core mac isn't idle during serial steps. Jobs are
distributed across multiple self-hosted runner **instances** on the same machine.

## One-time setup
Register 3 extra runners (the existing `gustavo-mac-local` + 3 = 4 total):
```bash
scripts/ci/setup-runners.sh        # default 3 extras; needs gh auth
```
Verify they're online:
```bash
gh api repos/humangr-labs/HuGR-Arsenal/actions/runners -q '.runners[] | "\(.name): \(.status)"'
```

## How it works
- A `setup` job builds a **shared venv** once at `$HOME/.hugr-ci-venv` (rebuilt only
  when `requirements-mcp.txt` changes — persistent runners reuse it).
- 6 test jobs `needs: setup` and run concurrently across the runners → wall time ≈
  the slowest job, not the sum.
- `unit` is capped at `-n 6` to avoid CPU oversubscription with the other concurrent jobs.

## Persistence (optional)
`nohup ./run.sh` runners die on reboot. For boot-persistent runners, in each
`~/actions-runner-N`: `sudo ./svc.sh install && sudo ./svc.sh start`.

## Dev loop
Don't wait on CI. The gate is local: `make verify` (tiered). CI is the async
backstop — merge on local green, fix-forward if CI pings red.
