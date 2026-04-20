# SkillEngine — primitive delivery pipeline

Inviolable, 9-tier, contract-gated. Zero soft-accept.

## Layout

```
engine/
├── contracts/
│   └── primitive_delivery_contract.py   # 40+ Pydantic validators, 9 tiers
├── llm/
│   └── transport.py                      # claude CLI subprocess wrapper
├── gates/
│   └── runners.py                        # 9 tier gate runners
├── briefings/
│   └── builder_briefings.py              # 10 batch assignments (113 primitives)
├── check_primitive.py                    # per-primitive aggregator CLI
├── merge.py                              # catalog-wide roll-up + report
└── tests/
    ├── test_delivery_contract.py         # 84 meta-tests
    └── test_integration.py               # cross-namespace post-merge tests
```

## Tier cheat sheet

| Tier | Check | Applies to |
|---|---|---|
| T1 behavioral | end-to-end scenarios prove invariants | every primitive |
| T2 formal | TLA+ / Alloy model check | stateful primitives only |
| T3 state-machine | hypothesis `RuleBasedStateMachine` | stateful primitives only |
| T4 metamorphic | algebraic laws + differential parity | every primitive |
| T5 concurrency | linearizability + deterministic scheduler | stateful primitives only |
| T6 adversarial | ≥3 Claude models × ≥20 attacks, 0 successful | every primitive |
| T7 observability | log / metric / span schema assertions | every primitive |
| T8 chaos | fault injection + game-day scripts | every primitive |
| T9 meta | LLM judge ≥8/10 × 6 axes + 5 personas understood | every primitive |

`experimental` primitives require: T1 + T6.
`emerging`: T1, T3, T4, T6, T7.
`battle_tested`: all 9.

## Per-primitive workflow

1. Builder agent receives batch briefing (see `briefings/builder_briefings.py::BRIEFINGS`).
2. For each primitive: implement + tests + observability + spec + contract.json + invariant_bindings.json.
3. Run `python3 -m engine.check_primitive --primitive-dir ... --catalog-entry ... --maturity ... --builder-agent N --invariant-bindings ...`.
4. Iterate until exit 0.
5. Final artefact: `<Name>.manifest.json` in primitive dir.

## Post-delivery (all 10 batches done)

```
python3 -m engine.merge --venous-root skills/SKILL-001-fastapi-production/core/venous
pytest skills/SKILL-001-fastapi-production/engine/tests/test_integration.py -q
```

## Non-negotiables

- 40+ Pydantic validators enforce schema + cross-field rules.
- 84 meta-tests prove the contract accepts valid deliveries and rejects every
  specific failure mode.
- `accept_delivery()` returns `(False, None, [errors])` on any violation; no
  soft-accept path exists.
- Tier runners ERRORED on missing external tools (tlc, alloy); the aggregator
  treats ERRORED as rejection.
- `_sanity_check` in `briefings/` asserts the 10-batch partition is complete
  and disjoint at import time.
