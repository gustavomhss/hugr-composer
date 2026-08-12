# Design Document: Claude Code Gateway (claude-gateway)

**Status**: Frozen  
**Author**: Auto-generated from research  
**Date**: 2026-08-11  
**Target**: Single-file FastAPI gateway (~400 LOC) enabling native `/model` picker + subagent spawn for 6 independent provider groups.

---

## 1. Problem Statement

Claude Code's native model picker (`/model`) and subagent `model:` frontmatter only accept Anthropic model aliases (fable/opus/sonnet/haiku) or IDs recognized by the provider. To make models from **OpenRouter, Groq, Google AI Studio (Gemini), NVIDIA NIM, Mistral** and **opencode-configured providers** appear as first-class picker entries and be spawnable exactly like native models — **zero friction, zero overhead, zero unnecessary complexity** — we need a minimal local gateway that:

1. Speaks Anthropic Messages API (`/v1/messages`, `/v1/models`)
2. Registers with Claude Code via `ANTHROPIC_BASE_URL` + `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`
3. Routes requests to six independent provider groups with minimal translation:
   - **OpenRouter**: pass-through to Anthropic Skin (zero translation)
   - **Groq**: thin Anthropic↔OpenAI translation
   - **Google AI Studio (Gemini)**: thin Anthropic↔Gemini translation (free tier)
   - **NVIDIA NIM**: thin Anthropic↔OpenAI translation (self-hosted or cloud)
   - **Mistral**: thin Anthropic↔OpenAI translation (free tier)
   - **opencode-bridge**: thin Anthropic↔OpenAI translation → opencode-bridge instances (one per provider) → opencode serve (uses providers from opencode's auth.json)

Each provider group = independent quota/keys/billing. opencode-bridge reuses opencode's configured providers (keys in `~/.local/share/opencode/auth.json`).

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Claude Code / IDE                                                       │
│  ANTHROPIC_BASE_URL=http://127.0.0.1:8787                               │
│  CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1                           │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ HTTP (Anthropic Messages API)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  claude-gateway (FastAPI, ~400 LOC)                                     │
│  ─────────────────────────────────────                                  │
│  GET  /v1/models           → Discovery endpoint (IDs with "claude/")   │
│  POST /v1/messages         → Router (health-aware, fallback-capable):  │
│       ├─ claude-openrouter-*  → OpenRouter (Anthropic Skin pass-through)│
│       ├─ claude-groq-*        → Groq (OpenAI Chat Completions + translation)│
│       ├─ claude-gemini-*      → Google AI Studio (Generative AI API + translation)│
│       ├─ claude-nim-*         → NVIDIA NIM (OpenAI-compatible + translation)│
│       ├─ claude-mistral-*     → Mistral API (OpenAI-compatible + translation)│
│       └─ claude-opencode-*    → opencode-bridge instances (OpenAI-compatible + translation)│
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  OpenRouter      │   │  Groq            │   │  Google AI Studio│
│  api.openrouter. │   │  api.groq.com    │   │  generativelang- │
│  ai/api          │   │  /openai/v1/     │   │  uage.googleapis │
│  (Anthropic Skin)│   │  (OpenAI format) │   │  .com/v1beta/    │
│  Pass-through    │   │  Translation     │   │  (Gemini format) │
└──────────────────┘   └──────────────────┘   └──────────────────┘
        ▲                        ▲                        ▲
        └────────────────────────┼────────────────────────┘
                                 ▼                        ▼
                        ┌──────────────────┐   ┌──────────────────┐
                        │  NVIDIA NIM      │   │  Mistral API     │
                        │  <host>/v1/      │   │  api.mistral.ai  │
                        │  (OpenAI format) │   │  /v1/            │
                        │  Translation     │   │  (OpenAI format) │
                        └──────────────────┘   └──────────────────┘
                                 ▲                        ▲
                                 └────────────────────────┘
                                                             │
                    ┌────────────────────────────────────────┼────────────────────────────────────────┐
                    ▼                                        ▼                                        ▼
            ┌──────────────────┐                     ┌──────────────────┐                     ┌──────────────────┐
            │ opencode-bridge  │                     │ opencode-bridge  │                     │ opencode-bridge  │
            │ :5001 (Groq)     │                     │ :5002 (Gemini)   │                     │ :5003 (Mistral)  │
            │ (OpenAI format)  │                     │ (OpenAI format)  │                     │ (OpenAI format)  │
            │ Translation      │                     │ Translation      │                     │ Translation      │
            └────────┬─────────┘                     └────────┬─────────┘                     └────────┬─────────┘
                     │                                        │                                        │
                     └────────────────────────────────────────┼────────────────────────────────────────┘
                                                              ▼
                                                    ┌──────────────────┐
                                                    │  opencode serve  │
                                                    │  :4096           │
                                                    │  providers from  │
                                                    │  auth.json       │
                                                    └──────────────────┘

*Six independent provider groups → independent quota/keys/billing.*
```

---

## 3. Gateway Model Discovery Contract

### 3.1 Discovery Filter (Claude Code v2.1.223+)

Claude Code queries `GET /v1/models?limit=1000` at startup. **Only entries whose `id` contains `claude` or `anthropic` (case-insensitive substring) are kept**. All others are silently dropped.

### 3.2 ID Naming Strategy

| Backend | Picker ID Pattern | Discovery Pass? | Maps To |
|---------|-------------------|-----------------|---------|
| OpenRouter (Anthropic) | `claude-openrouter-opus-5`, `claude-openrouter-sonnet-5` | ✅ | Pass-through → `anthropic/claude-opus-5` |
| OpenRouter (non-Anthropic) | `claude-openrouter-deepseek`, `claude-openrouter-qwen` | ✅ | Pass-through → `openrouter/provider/model` |
| Groq (direct) | `claude-groq-llama3`, `claude-groq-mixtral`, `claude-groq-gemma` | ✅ | Translation → `groq/model` |
| Google AI Studio (Gemini) | `claude-gemini-flash`, `claude-gemini-pro`, `claude-gemini-flash-8b` | ✅ | Translation → `gemini-1.5-flash` etc. |
| NVIDIA NIM | `claude-nim-llama3`, `claude-nim-nemotron`, `claude-nim-mixtral` | ✅ | Translation → NIM model |
| Mistral (direct) | `claude-mistral-large`, `claude-mistral-small`, `claude-mistral-codestral` | ✅ | Translation → `mistral-...` |
| opencode-bridge (Groq) | `claude-opencode-groq-llama3`, `claude-opencode-groq-mixtral` | ✅ | Translation → bridge:5001 → `groq/llama-3.3-70b-versatile` |
| opencode-bridge (Gemini) | `claude-opencode-gemini-flash`, `claude-opencode-gemini-pro` | ✅ | Translation → bridge:5002 → `gemini/gemini-1.5-flash` |
| opencode-bridge (Mistral) | `claude-opencode-mistral-large`, `claude-opencode-mistral-small` | ✅ | Translation → bridge:5003 → `mistral/mistral-large-latest` |

### 3.3 Response Format

```json
{
  "data": [
    { "id": "claude-openrouter-opus-5", "display_name": "Opus 5 (OpenRouter)" },
    { "id": "claude-openrouter-sonnet-5", "display_name": "Sonnet 5 (OpenRouter)" },
    { "id": "claude-groq-llama3", "display_name": "Llama 3.3 70B (Groq)" },
    { "id": "claude-gemini-flash", "display_name": "Gemini 1.5 Flash (Free)" },
    { "id": "claude-nim-llama3", "display_name": "Llama 3 (NIM)" },
    { "id": "claude-mistral-large", "display_name": "Mistral Large (Free)" },
    { "id": "claude-opencode-groq-llama3", "display_name": "opencode: Groq Llama 3" },
    { "id": "claude-opencode-gemini-flash", "display_name": "opencode: Gemini Flash" },
    { "id": "claude-opencode-mistral-large", "display_name": "opencode: Mistral Large" }
  ]
}
```

Cache: `~/.claude/cache/gateway-models.json`, refreshed on each startup.

---

## 4. Request Routing Logic

### 4.1 OpenRouter Pass-Through (Zero Translation)

For IDs matching `claude-openrouter-*`:

1. Extract model from request body `model` field, strip `claude-openrouter-` prefix
2. Rewrite via `openrouter_model_map` (e.g., `opus-5` → `anthropic/claude-opus-5`)
3. Forward `POST /v1/messages` to `https://openrouter.ai/api/v1/messages` **byte-for-byte**
4. Relay SSE stream back to client unchanged
5. Propagate `x-claude-code-session-id`, `x-claude-code-agent-id` headers

**Why this works**: OpenRouter's Anthropic Skin accepts native Anthropic Messages format. No translation needed.

### 4.2 Groq Direct (Thin Translation Layer)

For IDs matching `claude-groq-*`:

1. Extract model: `claude-groq-llama3` → `llama3` → map via `groq_model_map` to `llama-3.3-70b-versatile`
2. **Translate Anthropic → OpenAI Chat Completions**:
   - `messages[]`: system→`system`, user/assistant→same, tool_result→`tool` role with `tool_call_id`
   - `tools[]` → `functions` (OpenAI format) via shared `translator/tool_schema.py`
   - `thinking`/`thinking_config` → drop (Groq doesn't support)
   - `stream: true` → `stream: true`
3. POST to `https://api.groq.com/openai/v1/chat/completions` with `Authorization: Bearer $GROQ_API_KEY`
4. **Translate OpenAI SSE → Anthropic SSE**:
   - `choices[0].delta.content` → `content_block_delta` (text)
   - `choices[0].delta.tool_calls` → `content_block_delta` (tool_use, reconstructed via buffer)
   - `choices[0].finish_reason` → `message_stop`
5. Emit keep-alive `:` pings every 30s

**Translation scope**: Minimal — only message format + tool schema. No logic translation.

### 4.3 Google AI Studio (Gemini Free Tier) — Thin Translation Layer

For IDs matching `claude-gemini-*`:

1. Extract model: `claude-gemini-flash` → `flash` → map via `gemini_model_map` to `gemini-1.5-flash`
2. **Translate Anthropic → Google Generative AI API**:
   - `messages[]`: system→`system_instruction`, user/assistant→`contents[]` with `role` (`user`/`model`), tool_result→`functionResponse`
   - `tools[]` → `tools[]` with `functionDeclarations` via shared `translator/tool_schema.py`
   - `thinking` → drop (Gemini free tier doesn't support)
   - `stream: true` → `streamGenerateContent` (SSE)
3. POST to `https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key=$GEMINI_API_KEY`
4. **Translate Gemini SSE → Anthropic SSE**:
   - `candidates[0].content.parts[0].text` → `content_block_delta` (text)
   - `candidates[0].content.parts[0].functionCall` → `content_block_delta` (tool_use, reconstructed)
   - `candidates[0].finishReason` → `message_stop`
5. Emit keep-alive `:` pings every 30s

**Free tier limits**: 15 RPM, 1M TPM (flash), 2M TPM (pro). Gateway enforces local rate-limit header passthrough.

### 4.4 NVIDIA NIM (Thin Translation Layer)

For IDs matching `claude-nim-*`:

1. Extract model: `claude-nim-llama3` → `llama3` → map via `nim_model_map` to model name
2. NIM exposes OpenAI-compatible `/v1/chat/completions` at configured host
3. **Translate Anthropic → OpenAI** (same as Groq, via shared `translator/openai.py`)
4. POST to `$NIM_BASE_URL/v1/chat/completions` with `Authorization: Bearer $NIM_API_KEY`
5. **Translate OpenAI SSE → Anthropic SSE** (same as Groq, via shared `translator/openai.py`)

### 4.5 Mistral API Direct (Thin Translation Layer)

For IDs matching `claude-mistral-*`:

1. Extract model: `claude-mistral-large` → `large` → map via `mistral_model_map` to `mistral-large-latest`
2. Mistral API is OpenAI-compatible at `https://api.mistral.ai/v1/chat/completions`
3. **Translate Anthropic → OpenAI** (same as Groq, via shared `translator/openai.py`)
4. POST with `Authorization: Bearer $MISTRAL_API_KEY`
5. **Translate OpenAI SSE → Anthropic SSE** (same as Groq, via shared `translator/openai.py`)

**Free tier**: 500 RPM, 200K TPM (mistral-small), generous for dev.

### 4.6 opencode-bridge (Multi-Instance, Thin Translation Layer)

For IDs matching `claude-opencode-*`:

1. **Parse provider prefix**: `claude-opencode-groq-llama3` → provider=`groq`, model_key=`llama3`
2. **Route to correct bridge instance**: lookup `opencode_bridge_endpoints[provider]` → e.g., `http://localhost:5001`
3. **Translate Anthropic → OpenAI** (same as Groq, via shared `translator/openai.py`)
4. POST to bridge instance `$OPENCODE_BRIDGE_ENDPOINTS[provider]/v1/chat/completions`
5. Bridge forwards to `opencode serve` which uses provider from its `OPENCODE_PROVIDER_ID` env
6. **Translate OpenAI SSE → Anthropic SSE** (same as Groq, via shared `translator/openai.py`)

**Bridge instance config** (one per provider, managed externally):
```bash
# Groq bridge
docker run -d -p 5001:5000 \
  -e OPENCODE_URL=http://host.docker.internal:4096 \
  -e OPENCODE_PROVIDER_ID=groq \
  crazyboy24/opencode-bridge

# Gemini bridge
docker run -d -p 5002:5000 \
  -e OPENCODE_URL=http://host.docker.internal:4096 \
  -e OPENCODE_PROVIDER_ID=gemini \
  crazyboy24/opencode-bridge

# Mistral bridge
docker run -d -p 5003:5000 \
  -e OPENCODE_URL=http://host.docker.internal:4096 \
  -e OPENCODE_PROVIDER_ID=mistral \
  crazyboy24/opencode-bridge
```

**Key advantage**: Uses opencode's configured providers + keys from `~/.local/share/opencode/auth.json`. No separate keys needed in gateway.

---

## 5. Configuration

### 5.1 Environment Variables (gateway)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GATEWAY_PORT` | No | 8787 | Local port |
| `OPENROUTER_API_KEY` | Conditional | — | Required if using OpenRouter |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api` | Override endpoint |
| `GROQ_API_KEY` | Conditional | — | Required if using Groq |
| `GEMINI_API_KEY` | Conditional | — | Required if using Gemini |
| `NIM_BASE_URL` | Conditional | — | Required if using NIM |
| `NIM_API_KEY` | Conditional | — | Required if using NIM |
| `MISTRAL_API_KEY` | Conditional | — | Required if using Mistral |
| `GATEWAY_LOG_LEVEL` | No | `INFO` | Log level |

*Keys only required for providers you actually use.*

### 5.2 Model Mapping Config (`gateway_config.yaml`)

```yaml
# Provider endpoints for opencode-bridge (one per provider)
opencode_bridge_endpoints:
  groq: "http://localhost:5001"
  gemini: "http://localhost:5002"
  mistral: "http://localhost:5003"

# Model maps (keys = suffix after provider prefix)
openrouter_model_map:
  opus-5: "anthropic/claude-opus-5"
  sonnet-5: "anthropic/claude-sonnet-5"
  haiku-5: "anthropic/claude-3.5-haiku"
  deepseek: "deepseek/deepseek-chat"
  qwen-coder: "qwen/qwen-2.5-coder-32b-instruct"
  glm-5: "z-ai/glm-5.2"

groq_model_map:
  llama3: "llama-3.3-70b-versatile"
  mixtral: "mixtral-8x7b-32768"
  gemma: "gemma2-9b-it"

gemini_model_map:
  flash: "gemini-1.5-flash"
  pro: "gemini-1.5-pro"
  flash-8b: "gemini-1.5-flash-8b"

nim_model_map:
  llama3: "meta/llama-3.1-70b-instruct"
  nemotron: "nvidia/nemotron-3-ultra"
  mixtral: "mistralai/mixtral-8x7b-instruct-v0.1"

mistral_model_map:
  large: "mistral-large-latest"
  small: "mistral-small-latest"
  codestral: "codestral-latest"

opencode_bridge_model_map:
  groq:
    llama3: "groq/llama-3.3-70b-versatile"
    mixtral: "groq/mixtral-8x7b-32768"
  gemini:
    flash: "gemini/gemini-1.5-flash"
    pro: "gemini/gemini-1.5-pro"
  mistral:
    large: "mistral/mistral-large-latest"
    small: "mistral/mistral-small-latest"
```

Discovery endpoint auto-generates from this config + live `/v1/models` from each opencode-bridge instance.

---

## 6. Claude Code Client Configuration

### 6.1 Shell Profile (`.zshrc` / `.bashrc`)

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8787"
export ANTHROPIC_AUTH_TOKEN="sk-or-<OPENROUTER_KEY>"  # or any provider key
export ANTHROPIC_API_KEY=""
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
```

### 6.2 Project Settings (`.claude/settings.local.json`)

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787",
    "ANTHROPIC_AUTH_TOKEN": "sk-or-...",
    "ANTHROPIC_API_KEY": "",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"
  }
}
```

### 6.3 User Setup (one-time)

```bash
# 1. opencode serve (usa providers do auth.json)
opencode serve  # porta 4096

# 2. opencode-bridge instances (uma por provider)
docker run -d -p 5001:5000 \
  -e OPENCODE_URL=http://host.docker.internal:4096 \
  -e OPENCODE_PROVIDER_ID=groq \
  crazyboy24/opencode-bridge

docker run -d -p 5002:5000 \
  -e OPENCODE_URL=http://host.docker.internal:4096 \
  -e OPENCODE_PROVIDER_ID=gemini \
  crazyboy24/opencode-bridge

docker run -d -p 5003:5000 \
  -e OPENCODE_URL=http://host.docker.internal:4096 \
  -e OPENCODE_PROVIDER_ID=mistral \
  crazyboy24/opencode-bridge

# 3. gateway config aponta pros bridges
# gateway_config.yaml já tem opencode_bridge_endpoints mapeado
```

### 6.4 Verify

```bash
claude
> /status
Auth token: ANTHROPIC_AUTH_TOKEN
Anthropic base URL: http://127.0.0.1:8787

> /model
# Shows: fable, opus, sonnet, haiku + "From gateway" entries for all providers
```

---

## 7. Security & Operational Considerations

| Aspect | Decision |
|--------|----------|
| Auth | Gateway exposes no auth (local-only 127.0.0.1). Provider keys only in env. |
| CORS | Not needed (Claude Code connects directly). |
| Rate limiting | Deferred to providers; gateway passes `Retry-After` headers. Local rate-limit enforcement for free tiers (Gemini 15 RPM, Mistral 500 RPM). |
| Logging | Structured JSON to stderr. No PII. |
| Process isolation | All backends HTTP; opencode-bridge instances run as separate processes. |
| Timeout | Gateway enforces 10min max per request; providers have own limits. |
| Health | `GET /health` → 200 OK + backend reachability (checks each provider + each bridge instance). |
| Fallback | Router supports ordered fallback chain per provider group (configurable). |

---

## 8. Limitations (Explicit, Accepted)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Non-Anthropic tool-use reliability | Known caveat for Groq/Gemini/NIM/Mistral/opencode-bridge | Keep Anthropic via OpenRouter as primary; others for exploration |
| Discovery filter requires `claude/` prefix | Can't show raw provider IDs | Alias strategy documented |
| Single gateway process | No HA | Local dev tool; acceptable |
| Thinking blocks dropped on non-Anthropic | No extended reasoning on Groq/Gemini/NIM/Mistral/opencode-bridge | Document; use OpenRouter for reasoning models |
| opencode-bridge single provider per instance | Multiple providers = multiple bridge instances | Run multiple bridges on different ports; gateway routes by provider |
| Free tier rate limits | Gemini 15 RPM, Mistral 500 RPM | Gateway enforces local rate limiting; passes `Retry-After` |

---

## 9. Acceptance Criteria

1. `GET /v1/models` returns IDs with `claude`/`anthropic` substring for all 6 provider groups
2. `POST /v1/messages` with `model=claude-openrouter-opus-5` → proxies to OpenRouter, SSE relay works
3. `POST /v1/messages` with `model=claude-groq-llama3` → translates, streams from Groq
4. `POST /v1/messages` with `model=claude-gemini-flash` → translates, streams from Gemini free tier
5. `POST /v1/messages` with `model=claude-nim-llama3` → translates, streams from NIM
6. `POST /v1/messages` with `model=claude-mistral-large` → translates, streams from Mistral
7. `POST /v1/messages` with `model=claude-opencode-groq-llama3` → routes to bridge:5001, streams via opencode
8. `POST /v1/messages` with `model=claude-opencode-gemini-flash` → routes to bridge:5002, streams via opencode
9. `POST /v1/messages` with `model=claude-opencode-mistral-large` → routes to bridge:5003, streams via opencode
10. `/model` picker in Claude Code shows all configured entries labeled "From gateway"
11. Subagent with `model: claude-opencode-gemini-flash` spawns and returns result
12. Gateway starts in <2s, handles 5 concurrent streams, <50MB RSS
13. Health endpoint reports each backend + each bridge instance status
14. Fallback chain works when primary backend fails

---

## 10. Out of Scope

- Multi-user / remote access
- Tool-use marshaling (bidirectional Claude↔opencode tool loop) — not needed; opencode-bridge uses function calling
- Web UI / dashboard
- Auto-update / self-healing
- OAuth flows for providers (API keys only)