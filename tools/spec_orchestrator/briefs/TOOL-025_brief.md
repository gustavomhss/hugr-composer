## Tool: `add_factory`

### Overview parameters
- Tool name: `fastapi_add_factory`
- Category: EXTEND > Testing
- Complexity: Medium
- Dependencies: existing FastAPI project with SQLAlchemy models + pytest
- Signature: `add_factory(project_dir: str, models: list[str] | None = None, backend: Literal["factory_boy", "polyfactory"] = "polyfactory") -> dict`
- Parameters:
  - `project_dir`: project root path
  - `models`: list of model names to generate factories for (None = all models)
  - `backend`: which factory library — `polyfactory` (modern, Pydantic-first, default) or `factory_boy` (legacy)

### Purpose
Generate test data factories for every SQLAlchemy model in the project. Factories are parameterless callables (`ItemFactory.build()`) that return fully-valid model instances with realistic fake data (using Faker). Supports sub-factories for FK relationships, post-generation hooks for associations (many-to-many), batch generation (`ItemFactory.build_batch(50)`), and traits for common variants (`UserFactory.build(admin=True)`). Using polyfactory (default) for modern Pydantic integration. Eliminates the manual boilerplate of constructing test fixtures and keeps tests readable.

### Performance SLOs
- Tool execution time < 3s for up to 10 models
- Files modified ≤ 2
- Files created ≥ 5 (factories module, one factory per model, conftest integration, tests)
- Factory build latency < 1 ms per instance
- Batch of 100 instances < 50 ms
- FK relationships resolved via sub-factories (no extra DB calls in `build()`, only in `create()`)
- No changes to application source (tests-only tool)

### Key technical decisions
1. **Backend:** polyfactory (default) uses Pydantic schemas to infer types. factory_boy for legacy projects.
2. **One factory per model:** `tests/factories/item_factory.py` with `class ItemFactory(ModelFactory[Item]): __model__ = Item`.
3. **Realistic fake data:** `Faker.email()`, `Faker.name()`, `Faker.text(max_nb_chars=200)`. Each field type inferred from SQLAlchemy column type.
4. **Sub-factories:** for FK relationships, reference other factories. `owner = Use(UserFactory.build)`.
5. **Traits:** common variants as `@post_generated` methods or `Use(lambda: ...)` overrides.
6. **Batch:** `build_batch(N)` creates N instances. `create_batch(N, session=db)` persists them.
7. **Integration with conftest.py:** adds fixtures for each factory (e.g. `@pytest.fixture def item_factory():`).
8. **Faker locale:** default to `en_US`, configurable.
9. **No Alembic changes:** this is a tests-only tool.
10. **Idempotency:** re-run skips existing factory files.

### Key invariants
1. Every factory ALWAYS produces a model instance that passes all DB constraints (NOT NULL, CHECK, etc.).
2. FK relationships are ALWAYS resolved via sub-factories — never None unless nullable.
3. Factories NEVER hit the database in `build()` — only in `create()`.
4. `build_batch(N)` ALWAYS produces N unique instances.
5. Unique constraints (e.g. email) are ALWAYS respected via `Faker.unique`.
6. Factories NEVER modify application code — tests/ only.
7. Each field's fake value type ALWAYS matches the SQLAlchemy column type.

### User story themes
- 9.1 Basic factory (US-01..05): build, create, fields filled, FK resolved
- 9.2 Batch & traits (US-06..10): build_batch, admin trait, active trait, post-generation
- 9.3 FK & relationships (US-11..15): sub-factory, optional FK, nullable handling
- 9.4 Integration with tests (US-16..20): conftest fixtures, session binding, test using factory
- 9.5 Edge cases & idempotency (US-21..25): unique constraint, tool re-run, custom provider

### Test plan categories
- 10.1 Build (T-01..06): factory.build() returns instance, fields valid
- 10.2 Create (T-07..12): factory.create() persists, session commit
- 10.3 Relationships (T-13..18): FK resolved, sub-factory, nullable
- 10.4 Batch & uniqueness (T-19..24): build_batch, unique constraint, trait
- 10.5 Integration (T-25..30): fixture, conftest, tool idempotency

### Edge cases (15)
1. Model has no Pydantic schema → tool uses SQLAlchemy column types directly
2. Model with circular FK → tool detects and breaks cycle via `Use(lambda: None)` or omit
3. Column with CHECK constraint → tool uses appropriate fake (e.g. enum values)
4. Unique email field → `Faker.unique.email()`
5. Column with custom type (UUID, JSONB) → tool provides default generator
6. Self-referential FK (e.g. parent_id) → optional, defaults to None
7. Composite PK → tool supports via separate factory fields
8. Column with default value → factory respects default (omits unless explicitly set)
9. Model with no nullable fields → all fields required, factory fills all
10. Model name collides with Python keyword → tool sanitizes factory class name
11. Faker locale missing for a provider → falls back to en_US
12. Tool re-run idempotent
13. Model added after initial tool run → re-run creates new factory
14. Generated fields exceed column length → Faker `text(max_nb_chars=column_length)`
15. JSONB field with schema → tool uses random dict

### Anti-patterns
- DO NOT modify application source (tests/ only)
- DO NOT call `create()` in `build()` (no DB in build)
- DO NOT skip FK resolution (factories must produce valid instances)
- DO NOT use `Faker()` without locale in production tests
- DO NOT ignore unique constraints (use `Faker.unique`)
