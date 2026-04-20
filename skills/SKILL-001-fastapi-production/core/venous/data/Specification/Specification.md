# Specification

## What it does (plain language)

Specification is the composable-predicate primitive for every domain rule. It
packages one boolean test ("is this account dormant?", "is this order high
value?") as a named object you can AND, OR, and NOT together to express richer
policies — without rewriting the rule for in-memory filtering, validation, UI,
or SQL. One rule, used everywhere, with one meaning.

## Purpose

Encapsulate a predicate over a domain object so selection, validation, and
building criteria share one reusable rule.

## When to use and when NOT to use

- USE: any domain rule that shows up in more than one place (filter + validate,
  list + export, UI toggle + batch job). Eligibility criteria, segmentation
  rules, audit predicates.
- USE: any selection policy that must be testable without a database.
- DO NOT USE: one-off lambda filters that never leave a single function.
- DO NOT USE: stateful business workflows — Specifications are pure predicates,
  not commands or process managers.

## API surface

The catalog `api_signature` in `Specification.contract.json` is the authority.

```python
class Specification(Protocol, Generic[T]):
    def is_satisfied_by(self, candidate: T) -> bool: ...
    def and_(self, other: Specification[T]) -> Specification[T]: ...
    def or_(self, other: Specification[T]) -> Specification[T]: ...
    def not_(self) -> Specification[T]: ...
```

Callers build leaves (either by subclassing `BaseSpecification` and overriding
`is_satisfied_by`, or by passing a pure callable to `PredicateSpecification`),
then compose them with `and_`, `or_`, `not_`. `in_memory_filter` runs the
composed specification against an iterable. `TranslatorRegistry` converts the
tree to a backend-specific query representation without the Specification
itself knowing anything about the backend.

## Invariants

| ID | Rule |
|---|---|
| SPEC_INV_01 | `is_satisfied_by` MUST be a pure predicate — no I/O, no mutation, no hidden time dependence. |
| SPEC_INV_02 | Composed specifications MUST preserve boolean algebra laws (commutativity, associativity, idempotence, De Morgan, double negation, distributivity). |
| SPEC_INV_03 | A Specification CANNOT depend on the persistence layer; repository translation MUST live in a separate `TranslatorRegistry`. |
| SPEC_INV_04 | The same Specification used for in-memory filtering and repository querying SHALL produce logically equivalent results. |
| SPEC_INV_05 | Composition operators (`and_`, `or_`, `not_`) SHALL NOT be overridden by subclasses — only `is_satisfied_by` MAY be overridden. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `BaseSpecification` instances are immutable: once constructed they carry no
  mutable state, so they are trivially safe to share across threads and async
  tasks (SPEC-INV-01).
- `TranslatorRegistry` serialises register / translate calls via an internal
  lock. Concurrent registrations converge linearizably; concurrent translate
  calls read a snapshot of the backend map under the lock and evaluate the
  spec tree outside the lock so callbacks cannot deadlock.
- `in_memory_filter` is a pure function over the iterable and the spec.

## Operational characteristics (for SRE)

- Translator failures (missing leaf, missing backend) raise
  `SpecificationInvariantError` with the offending `(backend, leaf_name)` in
  the message — diagnose by grepping for the invariant-ID prefix.
- Self-observability: `spec.evaluations` (counter, `outcome` label),
  `spec.composition.depth` (histogram, `operator` label),
  `spec.translate.duration` (histogram, `backend` + `result` labels).
- A spike in `spec.translate.duration{result="error"}` points to an
  incompletely booted translator registry — usually a deployment that forgot
  to call `TranslatorRegistry.register` for a new leaf.

## Security considerations

- A Specification tree can be serialised to a backend query through the
  registry. The registry is the ONLY place where backend strings / fragments
  enter. Reviewers MUST audit every `TranslatorRegistry.register` call for
  string-interpolation of user input (SQL injection surface).
- Predicate callables passed to `PredicateSpecification` execute every time
  `is_satisfied_by` runs. They MUST be pure functions of the candidate.
  Passing a closure that reads a shared mutable state is a SPEC-INV-01
  violation and will surface as flaky filter results.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans — *Domain-Driven Design* (2003), Chapter 9, Specification pattern,
    pp. 224–240.
  - Fowler and Evans — *Specifications* white paper (2002), sections
    "Composite Specification" and "Querying".

## Alternatives considered and rejected

- Inline lambdas per callsite — duplicated logic and no composition algebra.
- Raw SQL fragments — storage-coupled and untestable in-memory.
- Rule-engine DSL — heavier than needed for the 80% case and opaque to domain
  experts.

## Extension contract

- New rules extend Specification by subclassing `BaseSpecification` and
  overriding `is_satisfied_by`, OR by wrapping a callable in
  `PredicateSpecification(name, fn)`.
- A new backend registers leaf translators via
  `TranslatorRegistry.register(backend, leaf_name, fn)` once at boot.
- Composition operators (`and_`, `or_`, `not_`) SHALL NOT be overridden — the
  algebra is closed and sealed (SPEC-INV-05); the base class enforces this at
  class-creation time.

## Schema of `Specification.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from Specification import PredicateSpecification, in_memory_filter

dormant = PredicateSpecification("dormant", lambda a: a.last_login_days > 180)
high_value = PredicateSpecification("high_value", lambda a: a.balance >= 100_000)

criterion = dormant.and_(high_value.not_())
eligible = in_memory_filter(criterion, accounts)
```

For a repository translation:

```python
from Specification import TranslatorRegistry

reg = TranslatorRegistry()
reg.register("sql", "dormant", lambda s: "last_login_days > 180")
reg.register("sql", "high_value", lambda s: "balance >= 100000")

query_tree = reg.translate("sql", criterion)  # => dict of AND / NOT / leaves
# Hand `query_tree` to your repository's SQL builder.
```

## Compose with:

- **Query + validate twins** → `Repository` + `Aggregate`
  The same Specification filters `find()` results and validates admission to an aggregate invariant — server-side and in-memory checks cannot drift.

- **Composable predicates** → `ValueObject` + `DataMapper`
  Spec composition (and/or/not) builds a new value object; the mapper translates the tree to the storage dialect on the fly.

- **Domain-only vocabulary** → `Repository` + `AntiCorruptionLayer`
  Specifications speak only domain terms; foreign filters are translated by the ACL before the repo ever sees them.
