# Writers Room — BYOK Multi-Provider Analysis

A rigorous comparison of every viable provider for Writers Room's two AI components (synthesis + embeddings), plus the recommended implementation pattern for letting users choose their own provider.

---

## Part 1: Synthesis Models (Replacing GPT-4o-mini)

Your synthesis task: 2-4 sentence grounded summary of 8 search results. ~1,400 input tokens, ~120 output tokens per call.

### Provider Comparison

| Provider | Model | Input/1M | Output/1M | Monthly cost (50 searches/day) | Context | Streaming | Free Tier | OpenAI-compatible API |
|---|---|---|---|---|---|---|---|---|
| **Groq** | Llama 3.1 8B | $0.05 | $0.08 | ~$0.07 | 128K | Yes | ~500K tok/day (no credit card) | Yes |
| **Google** | Gemini 2.5 Flash Lite | $0.10 | $0.40 | ~$0.21 | 1M | Yes | Yes (rate-limited) | No (own SDK) |
| **OpenAI** | GPT-4o-mini | $0.15 | $0.60 | ~$0.43 | 128K | Yes | No | Yes (native) |
| **Mistral** | Mistral Small 4 | $0.15 | $0.60 | ~$0.43 | 256K | Yes | Limited free tier | Yes |
| **DeepSeek** | V3 | $0.27 | $1.10 | ~$0.77 | 128K | Yes | 5M tokens on signup | Yes |
| **DeepSeek** | V3.2 | $0.28 | $0.42 | ~$0.42 | 128K | Yes | 5M tokens on signup | Yes |
| **Anthropic** | Claude Haiku 4.5 | $1.00 | $5.00 | ~$3.40 | 200K | Yes | No | No (own SDK) |

**Notes:**
- Groq is an inference provider running open-source models on custom LPU hardware. Extremely fast (>1,000 tok/s). The free tier alone covers ~300+ searches/day.
- Gemini 2.0 Flash / Flash Lite are being deprecated June 1, 2026. Use 2.5 Flash Lite instead.
- Claude Haiku 4.5 is 7-8x more expensive than GPT-4o-mini. Prompt caching (90% discount on repeated input) helps, but it's still the most expensive option.
- **Manus does NOT have a public LLM API.** It's an agent platform (acquired by Meta Dec 2025). Not a viable option for synthesis.

### Quality Assessment for Grounded Summarization

| Model | Expected quality | Notes |
|---|---|---|
| GPT-4o-mini | Excellent (baseline) | Current production model, proven |
| Gemini 2.5 Flash Lite | Very good | Google's latest lightweight; 1M context is overkill but ensures no truncation issues |
| Claude Haiku 4.5 | Excellent | Best instruction-following, but dramatically overpriced for this task |
| Mistral Small 4 | Very good | 119B MoE model, surprisingly capable |
| DeepSeek V3.2 | Good-to-very-good | Competitive quality, cheap output tokens |
| Llama 3.1 8B (Groq) | Good | Adequate for short grounded summaries; may miss nuance on complex queries |
| Llama 3.3 70B (Groq) | Very good | Better quality but $0.59/$0.79 per 1M tokens |

### Verdict: Best Options for Synthesis

1. **Default (free):** Groq + Llama 3.1 8B — free tier covers heavy daily use, streaming is lightning-fast
2. **Best quality/price:** Gemini 2.5 Flash Lite — $0.21/mo, great quality, massive context
3. **Current (proven):** GPT-4o-mini — $0.43/mo, known quantity
4. **Premium option:** Claude Haiku 4.5 — best instruction-following, but $3.40/mo is hard to justify

---

## Part 2: Embedding Models (Replacing text-embedding-3-small)

### Cloud Embedding APIs

| Provider | Model | Cost/1M tokens | Dimensions | Max Input | MTEB Score | Free Tier |
|---|---|---|---|---|---|---|
| **Mistral** | mistral-embed | $0.01 | 1,024 | 8K | 55.3 | No |
| **OpenAI** | text-embedding-3-small | $0.02 | 1,536 | 8,191 | 62.3 | No |
| **Jina AI** | jina-embeddings-v3 | ~$0.02 | 1,024 | 8,192 | ~65 | 10M tokens free |
| **Voyage AI** | voyage-3.5 | $0.06 | 1,024 | 32K | ~65 | **200M tokens free** |
| **Voyage AI** | voyage-3-large | $0.22 | 2,048 | 32K | ~65 | **200M tokens free** |
| **Google** | Gemini Embedding 001 | $0.15 | 3,072 | 8,192 | **68.3** (#1 MTEB) | 1,500 req/day free |
| **Cohere** | Embed v4 | $0.12 | 1,536 | 128K | 65.2 | 1,000 calls/mo |
| **OpenAI** | text-embedding-3-large | $0.13 | 3,072 | 8,191 | 64.6 | No |

**Key findings:**
- **Gemini Embedding 001 is #1 on MTEB** (68.3) — a significant quality lead over your current model (62.3)
- **Voyage AI has the best free tier** — 200M tokens covers full indexing of 5,800 notes multiple times over, for zero cost
- **Mistral-embed is cheapest** ($0.01/MTok) but quality (55.3) is noticeably behind
- Your current model (text-embedding-3-small) is mid-pack on quality but very cheap

### Local/On-Device Embedding Models

| Model | Parameters | Size | Dimensions | Max Input | MTEB | Notes |
|---|---|---|---|---|---|---|
| **nomic-embed-text-v1.5** | 137M | ~274 MB | 768 | **8,192** | ~65 | Best local option — matches your current context length |
| **nomic-embed-text-v2-moe** | 475M (305M active) | ~950 MB | 768 | 512 | ~66+ | Higher quality but short context |
| **BGE-small-en-v1.5** | 33.4M | ~67 MB | 384 | 512 | ~62 | Tiny, decent quality |
| **all-MiniLM-L6-v2** | 22.7M | ~80 MB | 384 | 256 | ~56 | Legacy — avoid for new projects |
| **Apple NLContextualEmbedding** | Built-in | 0 MB | 512 | 256 | Low | No download needed, but limited quality |

### Verdict: Best Options for Embeddings

1. **Best quality (cloud):** Gemini Embedding 001 — #1 MTEB, generous free tier (1,500 req/day)
2. **Best free tier (cloud):** Voyage AI voyage-3.5 — 200M free tokens, better quality than your current model
3. **Best local:** nomic-embed-text-v1.5 — 274 MB, 8,192 token context, ~65 MTEB (better than text-embedding-3-small)
4. **Current (reliable):** text-embedding-3-small — cheap, proven, but no longer quality leader

**Critical note on switching embeddings:** If you change the embedding model, you must **re-index all notes**. Different models produce incompatible vector spaces. This is a one-time operation but it's a migration, not a hot-swap.

---

## Part 3: The Multi-Provider Implementation

### The OpenAI-Compatible Base URL Pattern (Recommended)

The single most important insight: **most providers expose OpenAI-compatible endpoints**. You can use the `openai` Python SDK you already depend on and just swap `base_url` + `api_key`:

```python
from openai import OpenAI

PROVIDERS = {
    "openai":    {"base_url": None,                                      "model": "gpt-4o-mini"},
    "groq":      {"base_url": "https://api.groq.com/openai/v1",         "model": "llama-3.1-8b-instant"},
    "mistral":   {"base_url": "https://api.mistral.ai/v1",              "model": "mistral-small-latest"},
    "deepseek":  {"base_url": "https://api.deepseek.com/v1",            "model": "deepseek-chat"},
    "together":  {"base_url": "https://api.together.xyz/v1",            "model": "meta-llama/Llama-3.1-8B-Instruct"},
    "fireworks": {"base_url": "https://api.fireworks.ai/inference/v1",   "model": "accounts/fireworks/models/llama-v3p1-8b-instruct"},
    "openrouter":{"base_url": "https://openrouter.ai/api/v1",           "model": "openai/gpt-4o-mini"},
    "local":     {"base_url": "http://localhost:11434/v1",               "model": "llama3.1"},
}

def get_client(provider_name, api_key):
    provider = PROVIDERS[provider_name]
    kwargs = {"api_key": api_key}
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]
    return OpenAI(**kwargs), provider["model"]
```

**What this covers:** OpenAI, Groq, Mistral, DeepSeek, Together AI, Fireworks, DeepInfra, OpenRouter (500+ models via single key), Ollama, LM Studio — zero new dependencies.

**What this does NOT cover:** Anthropic and Google have their own SDK/API shapes. For these, either:
- Add `anthropic` and `google-generativeai` SDKs directly (two extra deps)
- Use Mozilla's `any-llm` library — modular installs (`pip install 'any-llm-sdk[anthropic]'`), normalizes responses to OpenAI format

### How Other Mac Apps Handle BYOK

Researched: BoltAI, Msty, MindMac, macai (open-source). Common patterns:

| Pattern | Details |
|---|---|
| **Settings pane** | Dedicated provider list in preferences |
| **Per-provider fields** | API key + optional custom endpoint URL |
| **Key storage** | Apple Keychain (native, encrypted) — use `keyring` in Python or Security framework |
| **Direct-to-provider** | API calls go directly from the app to the provider (no middleman) |
| **Model selector** | Dropdown that populates based on chosen provider |

### Library Options for Multi-Provider

| Library | Dependency footprint | Providers | For desktop app? |
|---|---|---|---|
| **OpenAI SDK + base_url** | 0 new deps (you already have `openai`) | ~80% of providers | Perfect |
| **any-llm (Mozilla)** | Modular — install only what you need | All major providers | Good — lightweight |
| **LiteLLM** | Heavy — pulls boto3, aioboto3, 20+ deps | 100+ providers | Too bloated |

### Recommended Implementation for Writers Room

**Tier 1 (ship first):** OpenAI SDK base_url pattern
- Covers: OpenAI, Groq, Mistral, DeepSeek, Together, Fireworks, OpenRouter, Ollama
- Zero new dependencies
- Config stored in preferences with key in Apple Keychain

**Tier 2 (add if demand):** Direct SDK integration
- Add `anthropic` SDK for Claude
- Add `google-generativeai` for Gemini
- Two small, well-maintained dependencies

**Tier 3 (optional):** OpenRouter as "universal" option
- Single API key accesses 500+ models
- Good fallback for users who don't want to manage multiple keys

---

## Part 4: Putting It All Together — Recommended Architecture

### Default Experience (Zero Keys, Zero Cost)

```
Indexing:    nomic-embed-text-v1.5 (local, bundled ~274 MB)
             OR Voyage AI (200M free tokens — enough for years)
Queries:     Same local model for query embedding
Synthesis:   Apple Foundation Models (macOS 26+, on-device)
             OR Groq free tier (Llama 3.1 8B, no credit card needed)
```

### BYOK Experience (Power Users)

```
Settings → Providers:
┌─────────────────────────────────────────────────┐
│  Synthesis Provider                              │
│  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ Groq       ▼ │  │ gsk-abc123...          │ │
│  └──────────────┘  └──────────────────────────┘ │
│                                                   │
│  Embedding Provider                               │
│  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ OpenAI     ▼ │  │ sk-xyz789...           │ │
│  └──────────────┘  └──────────────────────────┘ │
│                                                   │
│  [Test Connection]          [Save to Keychain]    │
└─────────────────────────────────────────────────┘
```

Users can mix and match: Groq for synthesis + OpenAI for embeddings, or Gemini for both, etc.

### The "Best Defaults" Configuration Matrix

| User Profile | Synthesis | Embeddings | Cost | Setup Effort |
|---|---|---|---|---|
| **Free, zero-config** | Apple Foundation Models | nomic-embed-text (local) | $0 | None |
| **Free, cloud** | Groq free tier | Voyage AI free tier | $0 | 2 API keys |
| **Cheapest paid** | Groq Llama 3.1 8B | Mistral-embed | ~$0.10/mo | 2 API keys |
| **Best quality** | GPT-4o-mini or Haiku 4.5 | Gemini Embedding 001 | $0.50-3.50/mo | 2 API keys |
| **Single provider** | Gemini 2.5 Flash Lite | Gemini Embedding 001 | ~$0.25/mo | 1 API key |
| **Fully offline** | Apple Foundation Models | nomic-embed-text (local) | $0 | None |

### The Single-Provider Sweet Spot: Google

Google is uniquely attractive because they offer both a competitive synthesis model AND the #1 embedding model, with a free tier for both:
- **Gemini 2.5 Flash Lite** for synthesis ($0.10/$0.40 per 1M tokens)
- **Gemini Embedding 001** for embeddings ($0.15 per 1M tokens, 1,500 free req/day)
- One API key, one provider, one billing relationship
- Free tier covers casual use entirely

---

## Part 5: Pro Feature Implications

The multi-provider BYOK itself becomes a feature differentiator:

**Free tier:**
- Apple Foundation Models synthesis (on-device)
- Local embeddings (nomic-embed-text, bundled)
- Up to 1,000 notes indexed

**Pro tier ($24.99 one-time):**
- Unlimited notes
- BYOK: Choose from 8+ synthesis providers (OpenAI, Claude, Gemini, Groq, Mistral, DeepSeek, OpenRouter, local)
- BYOK: Choose from 6+ embedding providers (OpenAI, Google, Voyage, Cohere, Mistral, Jina)
- HyDE deep search
- URL search
- Smart folders & saved searches
- Custom themes
- Topic map visualization

The free-to-Pro upgrade path is natural: local AI works great, but if you want GPT-4o-mini quality or Gemini's #1-ranked embeddings, bring your own key.
