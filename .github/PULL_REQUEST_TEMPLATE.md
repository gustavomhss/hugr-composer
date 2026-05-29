<!-- PR title MUST be a conventional commit (it becomes the squash commit on main). -->

## What
<!-- One-line summary of the change. -->

## Why
<!-- Context and motivation. Link the issue / WP / ADR. -->

## How
<!-- Implementation approach + key design decisions. Note anything out of scope. -->

## Testing
<!-- Paste the verbatim tail of the gates you ran (`make verify` tier, regression gates, contract_check). -->
```
<gate output>
```

## Definition of Done
- [ ] `make verify` green for the affected tier (output pasted above) — entrypoint is the repo-root `Makefile` (`make verify` / `verify-tier0` / `verify-tier1` / `verify-tier2`), which delegates to `skills/SKILL-001-fastapi-production/scripts/verify.sh`. There is NO repo-root `scripts/verify.sh`.
- [ ] Regression gates pass (`tests/test_p0_regression_gates.py`)
- [ ] No file outside the intended scope touched (`git diff --name-only`)
- [ ] No new narrative markdown outside `docs/`; no committed venv/emitted/db
- [ ] Logic files within the size cap (templates externalized)
- [ ] Honest behavior: no tool reports success for something it doesn't enforce
- [ ] ADR added/updated if this is an architectural decision
- [ ] Self-reviewed the diff as an adversarial reviewer
