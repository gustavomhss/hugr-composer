# LLM Domain — Maintenance Skill

> **Crates**: 1 (`LlmTrace`) | **Status**: Production-ready | **Owner**: AI/ML Team | **Last Updated**: 2026-09-04

> **Purpose**: LLM request/response tracing, cost tracking, and prompt observability.

---

## Crate: `LlmTrace`

**Location**: `core/venous/obs/LlmTrace/`

**Purpose**: Comprehensive LLM observability — request/response tracing, token counting, cost tracking, and prompt versioning.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      LLM OBSERVABILITY                      │
├─────────────────────────────────────────────────────────────┤
│  Request → LlmTrace Middleware → Provider SDK              │
│       ↓                                                      │
│  Trace Context → Spans → Token Counting → Cost Calc        │
│       ↓                                                      │
│  Prompt Versioning → Response Logging → Cost Aggregation   │
└─────────────────────────────────────────────────────────────┘
```

---

## Crate: `LlmTrace`

**Purpose**: Complete LLM observability — tracing, token counting, cost tracking, prompt versioning, and structured logging.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM OBSERVABILITY                        │
├─────────────────────────────────────────────────────────────┤
│  Request → LlmTrace Middleware → Provider SDK              │
│       ↓                                                      │
│  Trace Context → Spans → Token Counting → Cost Calc        │
│       ↓                                                      │
│  Prompt Versioning → Response Logging → Cost Aggregation   │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 1. Request/Response Tracing

```python
from generators.observability.llm_trace import LlmTraceMiddleware

# Add to FastAPI
app.add_middleware(LlmTraceMiddleware, 
    service_name="my-service",
    tracer=tracer,
    meter=meter,
)

# Automatic tracing for OpenAI, Anthropic, etc.
response = await openai.ChatCompletion.acreate(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello"}],
)

# Automatic span created with:
# - model: "gpt-4"
# - prompt_tokens: 10
# - completion_tokens: 50
# - total_tokens: 60
# - cost_usd: 0.0012
# - latency_ms: 1200
```

---

### 2. Token Counting & Cost Tracking

```python
from generators.observability.llm_trace import LlmCostTracker

tracker = LlmCostTracker(
    pricing={
        "gpt-4": {"input": 0.03, "output": 0.06},  # per 1K tokens
        "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
        "claude-3-opus": {"input": 0.015, "output": 0.075},
    }
)

# Automatic tracking via middleware
# Or manual tracking
cost = tracker.calculate_cost(
    model="gpt-4",
    prompt_tokens=1000,
    completion_tokens=500,
)
# Returns: {"input_cost": 0.03, "output_cost": 0.03, "total": 0.06}
```

---

### 3. Prompt Versioning

```python
from generators.observability.llm_trace import PromptRegistry

registry = PromptRegistry()

# Register prompt versions
registry.register(
    name="summarize_article",
    version="1.2",
    template="Summarize this article in 3 sentences: {article}",
    model="gpt-4",
    temperature=0.3,
    max_tokens=200,
)

# Use in code
prompt = registry.get("summarize_article", version="1.2")
response = await openai.ChatCompletion.acreate(
    model=prompt.model,
    messages=[{"role": "user", "content": prompt.template.format(article=article)}],
    temperature=prompt.temperature,
    max_tokens=prompt.max_tokens,
)

# Track which version was used
tracker.record_prompt_use("summarize_article", "1.2", tokens_used=150)
```

---

### 4. Structured Logging

```python
# Automatic structured logging for every LLM call
{
    "timestamp": "2026-09-04T10:30:00.123Z",
    "level": "INFO",
    "event": "llm_request",
    "model": "gpt-4",
    "prompt_version": "summarize_article:1.2",
    "prompt_tokens": 1200,
    "completion_tokens": 150,
    "total_tokens": 1150,
    "cost_usd": 0.042,
    "latency_ms": 2340,
    "user_id": "user_123",
    "request_id": "req_abc123",
    "trace_id": "trace_abc123",
    "span_id": "span_def456",
}
```

---

## Common Operations

### 1. Adding a New Model

```python
# Update pricing in cost tracker
tracker.update_pricing({
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},  # per 1K tokens
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
}

# Update prompt registry
registry.register(
    name="analyze_sentiment",
    version="1.0",
    template="Analyze sentiment: {text}",
    model="gpt-4-turbo",
    temperature=0.1,
    max_tokens=100,
)
```

### 2. Custom Cost Alerts

```python
# Alert on cost thresholds
@app.on_event("startup")
async def setup_cost_alerts():
    cost_monitor = CostMonitor(
        daily_budget_usd=100.0,
        alert_threshold=0.8,  # 80% of budget
        alert_webhook=settings.ALERT_WEBHOOK,
    )
    
    # Check every minute
    asyncio.create_task(cost_monitor.monitor_loop())
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Untracked model** | Cost not tracked | Add model to pricing config |
| **Prompt version drift** | Inconsistent outputs | Pin prompt versions; use registry |
| **Cost spike** | Budget exceeded | Set daily/monthly budgets + alerts |
| **Token counting mismatch** | Cost inaccurate | Use provider's tokenizer; verify counts |
| **Prompt drift** | Quality degradation | Version prompts; track performance per version |

---

## Evolution Without Breaking Contracts

### Adding a New Model

```python
# Non-breaking: add to pricing config
tracker.update_pricing({
    "new-model": {"input": 0.005, "output": 0.015},
}
```

### Adding Prompt Version

```python
# Non-breaking: new version
registry.register(
    name="analyze_sentiment",
    version="2.0",
    template="Analyze sentiment (v2): {text}",
    model="gpt-4-turbo",
)
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| New model with different pricing | **REVIEW** — Cost impact |
| Major prompt rewrite | **REVIEW** — Quality regression risk |
| Changing default model | **REVIEW** — Cost + quality impact |
| Removing prompt version | **STOP** — Breaking for users |

---

## Health Checks & Monitoring

```python
@app.get("/health/llm")
async def llm_health():
    return {
        "status": "healthy",
        "checks": {
            "openai_api": await check_openai_api(),
            "anthropic_api": await check_anthropic_api(),
            "cost_tracker": await check_cost_tracker(),
            "prompt_registry": await check_prompt_registry(),
        }
    }

# Metrics:
# - llm.requests.total
# - llm.tokens.prompt
# - llm.tokens.completion
# - llm.cost.usd
# - llm.latency.p99
# - llm.errors.rate
```

---

## Debugging Quick Reference

```bash
# View recent LLM calls
python -c "
from app.observability import get_recent_llm_calls
for call in get_recent_llm_calls(10):
    print(f'{call.model} | {call.prompt_tokens}+{call.completion_tokens} | ${call.cost:.4f} | {call.latency_ms}ms')
"

# Check costs
python -c "
from app.observability import get_cost_summary
print(get_cost_summary(last_hours=24))
"

# Check prompt versions
python -c "
from app.observability import get_prompt_versions
for name, versions in get_prompt_versions().items():
    print(f'{name}: {versions}')
"

# Debug specific request
python -c "
from app.observability import get_llm_call
call = get_llm_call('req_abc123')
print(f'Prompt: {call.prompt[:100]}...')
print(f'Response: {call.response[:100]}...')
print(f'Tokens: {call.prompt_tokens}+{call.completion_tokens}')
print(f'Cost: ${call.cost:.4f}')
"
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Request timeout | `timeout` | 30-60s |
| Max tokens | `max_tokens` | 2000-4000 |
| Temperature | `temperature` | 0.0-1.0 |
| Timeout budget | `timeout_budget` | 30-60s |
| Retry attempts | `max_retries` | 2-3 |

---

## Security Checklist

- [ ] No PII in prompts (or redacted)
- [ ] API keys in vault (not code)
- [ ] Rate limiting on LLM endpoints
- [ ] Cost budgets with alerts
- [ ] Prompt injection protection
- [ ] Output validation/sanitization
- [ ] Audit logging for all LLM calls
- [ ] Prompt versioning enforced
- [ ] Cost budgets with alerts
- [ ] Token counting verified

---

*LLM Domain Maintenance Skill v1.0 | Maintained by AI/ML Team | Next review: 2026-12-04*