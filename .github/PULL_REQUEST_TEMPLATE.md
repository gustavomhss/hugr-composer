<!--
HuGR SkillKit PR template — CONTRACT.md §C2 enforcement.

All six fields below are MANDATORY. Missing any field = PR REJECTED.
This is not optional. Read CONTRACT.md if unfamiliar.
-->

## Phase

<!-- Which §B item does this PR close? Format: `Phase N.K`. Example: `Phase 1.3`. -->

Phase:

## §A compliance

<!-- Which §A rules did this PR touch? For each, state how the rule remains satisfied after this change. At minimum list A1/A2/A5/A6/A7/A8 if any code / doc / primitive / tool was changed. -->

-

## DoD

<!-- Copy the Definition of Done block from the §B item, check each sub-item ✓ done or N/A with reason. -->

-

## Invariants

<!-- Copy the Invariants block; assert each still holds. -->

-

## Completeness

<!-- Copy the Completeness criteria; confirm scope boundary respected. -->

-

## Quality (SOTA)

<!-- Copy the Quality standards; describe how this PR meets each. Be specific. No "looks good" - show. -->

-

## Machine check

```bash
cd skills/SKILL-001-fastapi-production \
  && PYTHONPATH=. python3 -m engine.audit.contract_check
```

Paste the tail of the output:

```
<paste here>
```

## Notes

<!-- Anything else a reviewer should know. Keep terse. -->
