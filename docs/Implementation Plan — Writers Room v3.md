# Implementation Plan — Writers Room v3

---

## Codebase Strategy: Single Codebase + Feature Gating

**Yes — one codebase, one branch, one build.** Do NOT maintain separate free/pro branches or builds. Here's why and how:

### Why Single Codebase

| Approach | Maintenance burden | Risk |
|---|---|---|
| Separate branches (free/pro) | 2x — every bug fix, every UI change must be applied twice | Drift, merge hell, missed patches |
| Separate builds | Complex build pipeline, easy to ship wrong features to wrong tier | Accidental feature leaks |
| **Single codebase + feature gate** | **1x — one truth, one build, one deploy** | **Minimal — gating is a simple boolean check** |

### How Feature Gating Works

```python
# license.py — the single source of truth for tier status

import json
import os
from pathlib import Path

LICENSE_PATH = Path.home() / ".writersroom" / "license.json"

def is_pro() -> bool:
    """Check if user has active Pro license."""
    if not LICENSE_PATH.exists():
        return False
    try:
        data = json.loads(LICENSE_PATH.read_text())
        # Validate: key format, expiry (for trial), signature
        return data.get("status") == "active"
    except Exception:
        return False

def note_limit() -> int:
    """Return max indexable notes for current tier."""
    return 999_999 if is_pro() else 1_000

def require_pro(feature_name: str) -> bool:
    """Gate check. Returns True if allowed, raises/shows upgrade prompt if not."""
    if is_pro():
        return True
    # Trigger upgrade prompt in UI
    show_upgrade_prompt(feature_name)
    return False
```

Every gated feature calls `require_pro()` or checks `is_pro()`:

```python
# In indexer.py
if len(notes) > note_limit():
    notes = notes[:note_limit()]
    show_limit_reached_message()

# In synthesizer.py — BYOK provider selection
if provider != "local" and not is_pro():
    show_upgrade_prompt("Cloud AI providers")
    provider = "local"  # fall back

# In search — HyDE
if mode == "hyde" and not require_pro("HyDE deep search"):
    mode = "hybrid"  # fall back to hybrid
```

### License Validation (Offline-First)

Since this is a local-first app, license validation must work offline:

1. **Purchase:** User buys via Gumroad / Paddle / LemonSqueezy → receives a license key
2. **Activation:** User pastes key in Preferences → app validates against vendor API (one-time online check)
3. **Storage:** Validated license saved to `~/.writersroom/license.json` with a cryptographic signature
4. **Offline check:** App verifies the local signature on launch — no network needed after initial activation
5. **Trial:** On first install, auto-create a trial license (7 days, no key needed)

Recommended vendor: **LemonSqueezy** — handles payments, license key generation, activation API, and Mac App Store alternative distribution. One-time purchase support built in.

---

## Phase 1: Local-First Foundation (Weeks 1-3)

**Goal:** Replace all cloud dependencies with local alternatives. The app works with zero API keys.

### 1.1 Bundle Local Embedding Model

**Files to create/modify:**
- `models/` directory — store or download nomic-embed-text-v1.5
- `local_embedder.py` — new file, wraps sentence-transformers inference
- `indexer.py` — add `--provider local` flag, make it the default
- `server.py` — load local model for query embedding

**Implementation:**

```python
# local_embedder.py
from sentence_transformers import SentenceTransformer
import numpy as np

_model = None

def get_model():
    global _model
    if _model is None:
        # Path to bundled model or download on first run
        model_path = os.path.join(os.path.dirname(__file__), "models", "nomic-embed-text-v1.5")
        if os.path.exists(model_path):
            _model = SentenceTransformer(model_path)
        else:
            _model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5")
            _model.save(model_path)
    return _model

def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_model()
    # nomic requires "search_document: " prefix for documents, "search_query: " for queries
    return model.encode(texts, normalize_embeddings=True)

def embed_query(query: str) -> np.ndarray:
    model = get_model()
    return model.encode([f"search_query: {query}"], normalize_embeddings=True)[0]
```

**Key decisions:**
- Model downloads on first launch if not bundled (~274 MB)
- For py2app distribution, pre-bundle the model in the app package
- Embedding dimension changes from 1536 → 768, requiring a full re-index
- Add a migration flow: detect dimension mismatch in existing index → prompt re-index

**Tasks:**
- [ ] Create `local_embedder.py` with SentenceTransformer wrapper
- [ ] Modify `indexer.py` to accept `--provider` flag (local/openai/google/voyage/etc.)
- [ ] Modify `server.py` to use local embedder for query embedding by default
- [ ] Add dimension detection in index loader (handle 1536 vs 768 gracefully)
- [ ] Test search quality: run 20 representative queries, compare local vs OpenAI results
- [ ] Update py2app setup to bundle model files

### 1.2 Integrate Apple Foundation Models for Synthesis

**Files to create/modify:**
- `local_synthesizer.py` — new file, wraps Apple Foundation Models
- `synthesizer.py` — modify to dispatch between local and cloud providers

**Implementation approach:**
Apple Foundation Models are accessed via Swift/ObjC, not Python. Two options:

**Option A (recommended):** PyObjC bridge to Foundation Models framework
```python
# local_synthesizer.py
import objc
from Foundation import NSBundle

# Load FoundationModels framework
bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/FoundationModels.framework")
objc.loadBundle("FoundationModels", bundle_path=bundle.bundlePath())

# Use the on-device model for streaming synthesis
# Exact API depends on Apple's Python bridge availability
```

**Option B (fallback):** Shell out to a small Swift CLI tool bundled with the app
```python
import subprocess
result = subprocess.run(
    ["./tools/synthesize", "--prompt", prompt],
    capture_output=True, text=True
)
```

**Tasks:**
- [ ] Investigate PyObjC bridge to FoundationModels framework (macOS 26 beta)
- [ ] If PyObjC doesn't work cleanly, build a small Swift CLI for synthesis
- [ ] Add macOS version detection: `platform.mac_ver()` → gate Foundation Models availability
- [ ] Modify `synthesizer.py` to dispatch: local (macOS 26+) vs cloud (BYOK) vs disabled
- [ ] Test synthesis quality on representative queries
- [ ] Handle streaming output from Foundation Models → UI

### 1.3 Feature Gating Infrastructure

**Files to create/modify:**
- `license.py` — new file, license validation and tier checking
- `config.py` — new file, centralized app configuration
- `~/.writersroom/` — app data directory

**Tasks:**
- [ ] Create `license.py` with `is_pro()`, `note_limit()`, `require_pro()`
- [ ] Create `config.py` for provider settings, preferences, paths
- [ ] Add trial license auto-creation on first run (7-day Pro trial)
- [ ] Wire `note_limit()` into `indexer.py`
- [ ] Add upgrade prompt UI component (non-intrusive banner in results area)
- [ ] Set up LemonSqueezy account and product page

---

## Phase 2: BYOK Multi-Provider (Weeks 4-6)

**Goal:** Pro users can choose their AI provider for both synthesis and embeddings.

### 2.1 Provider Abstraction Layer

**Files to create/modify:**
- `providers.py` — new file, provider registry and client factory
- `synthesizer.py` — refactor to use provider abstraction
- `indexer.py` — refactor to use provider abstraction for embeddings

**Implementation:**

```python
# providers.py
from dataclasses import dataclass
from openai import OpenAI
import keyring

@dataclass
class ProviderConfig:
    name: str
    display_name: str
    base_url: str | None  # None = default OpenAI
    default_model: str
    requires_sdk: str  # "openai", "anthropic", "google", "local"
    supports_embeddings: bool
    supports_synthesis: bool

SYNTHESIS_PROVIDERS = {
    "local":      ProviderConfig("local", "On-Device (Apple)", None, "apple-foundationmodel", "local", False, True),
    "openai":     ProviderConfig("openai", "OpenAI", None, "gpt-4o-mini", "openai", False, True),
    "groq":       ProviderConfig("groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.1-8b-instant", "openai", False, True),
    "mistral":    ProviderConfig("mistral", "Mistral", "https://api.mistral.ai/v1", "mistral-small-latest", "openai", False, True),
    "deepseek":   ProviderConfig("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat", "openai", False, True),
    "together":   ProviderConfig("together", "Together AI", "https://api.together.xyz/v1", "meta-llama/Llama-3.1-8B-Instruct", "openai", False, True),
    "openrouter": ProviderConfig("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini", "openai", False, True),
    "ollama":     ProviderConfig("ollama", "Ollama (Local)", "http://localhost:11434/v1", "llama3.1", "openai", False, True),
    "anthropic":  ProviderConfig("anthropic", "Anthropic", None, "claude-haiku-4-5-20251001", "anthropic", False, True),
    "google":     ProviderConfig("google", "Google Gemini", None, "gemini-2.5-flash-lite", "google", False, True),
}

EMBEDDING_PROVIDERS = {
    "local":    ProviderConfig("local", "On-Device (nomic)", None, "nomic-embed-text-v1.5", "local", True, False),
    "openai":   ProviderConfig("openai", "OpenAI", None, "text-embedding-3-small", "openai", True, False),
    "google":   ProviderConfig("google", "Google Gemini", None, "models/gemini-embedding-001", "google", True, False),
    "voyage":   ProviderConfig("voyage", "Voyage AI", "https://api.voyageai.com/v1", "voyage-3.5", "openai", True, False),
    "mistral":  ProviderConfig("mistral", "Mistral", "https://api.mistral.ai/v1", "mistral-embed", "openai", True, False),
    "cohere":   ProviderConfig("cohere", "Cohere", None, "embed-v4", "cohere", True, False),
    "jina":     ProviderConfig("jina", "Jina AI", "https://api.jina.ai/v1", "jina-embeddings-v3", "openai", True, False),
}

def get_api_key(provider_name: str) -> str | None:
    """Retrieve API key from Apple Keychain."""
    return keyring.get_password("WritersRoom", f"{provider_name}_api_key")

def set_api_key(provider_name: str, key: str):
    """Store API key in Apple Keychain."""
    keyring.set_password("WritersRoom", f"{provider_name}_api_key", key)

def get_synthesis_client(provider_name: str):
    """Return appropriate client for the configured synthesis provider."""
    config = SYNTHESIS_PROVIDERS[provider_name]

    if config.requires_sdk == "local":
        from local_synthesizer import LocalSynthesizer
        return LocalSynthesizer()

    if config.requires_sdk == "anthropic":
        from anthropic import Anthropic
        return Anthropic(api_key=get_api_key(provider_name))

    if config.requires_sdk == "google":
        import google.generativeai as genai
        genai.configure(api_key=get_api_key(provider_name))
        return genai

    # OpenAI-compatible (covers 80% of providers)
    kwargs = {"api_key": get_api_key(provider_name)}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return OpenAI(**kwargs)
```

**Tasks:**
- [ ] Create `providers.py` with full provider registry
- [ ] Implement `keyring` integration for Apple Keychain storage
- [ ] Refactor `synthesizer.py` to use `get_synthesis_client()`
- [ ] Refactor `indexer.py` to use provider abstraction for embeddings
- [ ] Add `pip install anthropic google-generativeai keyring` to requirements
- [ ] Handle provider errors gracefully (invalid key, rate limit, network down)

### 2.2 Preferences UI — Provider Selection

**Files to modify:**
- `app.py` (or wherever the NSPanel UI lives) — add Preferences tab/panel

**UI layout:**
```
┌─ Preferences ──────────────────────────────────────────────┐
│                                                             │
│  AI Synthesis                                               │
│  ┌──────────────────┐  ┌────────────────────────────────┐  │
│  │ Groq           ▼ │  │ gsk-••••••••••••••••••••••   │  │
│  └──────────────────┘  └────────────────────────────────┘  │
│  Model: llama-3.1-8b-instant          [Test] [Save]        │
│                                                             │
│  AI Embeddings                                              │
│  ┌──────────────────┐  ┌────────────────────────────────┐  │
│  │ On-Device      ▼ │  │ No API key needed             │  │
│  └──────────────────┘  └────────────────────────────────┘  │
│  Model: nomic-embed-text-v1.5         [Save]               │
│                                                             │
│  ⚠️ Changing embedding provider requires re-indexing.       │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│  License                                                    │
│  Status: Pro (activated)                                    │
│  Key: XXXX-XXXX-XXXX-XXXX           [Manage License]       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Tasks:**
- [ ] Build Preferences NSPanel with provider dropdowns
- [ ] API key fields with show/hide toggle (masked by default)
- [ ] "Test Connection" — makes a minimal API call, shows green check or red X
- [ ] Warning banner when switching embedding provider (re-index required)
- [ ] License status display and activation field
- [ ] Save config to `~/.writersroom/config.json`

### 2.3 Re-indexing Flow

When the embedding provider changes, the entire index must be rebuilt (different vector dimensions/spaces).

**Tasks:**
- [ ] Detect provider change in config on app launch
- [ ] Show modal: "Embedding provider changed. Re-index required. This may take a few minutes."
- [ ] Run re-index in background thread with progress indicator
- [ ] Preserve old index until new one is complete (atomic swap)
- [ ] Handle partial re-index (if interrupted, resume from last folder)

---

## Phase 3: Pro Search & Output (Weeks 7-9)

### 3.1 HyDE Deep Search

**Concept:** For vague queries, generate a hypothetical answer first, embed that, and search with the expanded vector. This dramatically improves recall for abstract queries.

**Files to modify:**
- `server.py` — add `hyde` search mode
- `searcher.py` — implement HyDE pipeline

**Tasks:**
- [ ] Implement HyDE: query → synthesis provider generates hypothetical passage → embed passage → cosine search
- [ ] Blend HyDE vector with original query vector (configurable weight, default 0.7 HyDE / 0.3 original)
- [ ] Gate behind `require_pro("HyDE deep search")`
- [ ] Test on 20 vague queries, measure recall improvement vs standard semantic

### 3.2 Smart Folders / Saved Searches

**Tasks:**
- [ ] Data model: `{name, query, mode, filters, created, last_run}`
- [ ] Store in `~/.writersroom/saved_searches.json`
- [ ] UI: "Save this search" button in results header
- [ ] Sidebar or dropdown to access saved searches
- [ ] Auto-refresh results when a saved search is opened

### 3.3 "On This Day"

**Tasks:**
- [ ] Filter `metadata.json` for notes with `created` matching today's month+day in any year
- [ ] Show as a special view (triggered from menu bar dropdown or keyboard shortcut)
- [ ] Display with year grouping: "3 years ago", "1 year ago", etc.

### 3.4 Export

**Tasks:**
- [ ] Markdown export: format search results as a `.md` file with note titles, content excerpts, and links
- [ ] PDF export: use `reportlab` or `weasyprint` to render Markdown → PDF
- [ ] "Export" button in results header, file save dialog

---

## Phase 4: Visual Features & Polish (Weeks 10-12)

### 4.1 Topic Map

**Tasks:**
- [ ] K-means clustering: `sklearn.cluster.KMeans` on embedding vectors
- [ ] Auto-k selection via silhouette score (or let user choose)
- [ ] 2D projection: t-SNE or UMAP for visualization coordinates
- [ ] Render in an NSView with Core Graphics or a lightweight charting lib
- [ ] Interactive: hover for note title, click to open, color by cluster
- [ ] Auto-label clusters: most frequent title words or short GPT summary

### 4.2 Custom Themes

**Tasks:**
- [ ] Define theme schema: `{background, text, accent, border, panel_opacity}`
- [ ] Ship 5 built-in themes: Default Dark, Light, Warm (amber tones), Cool (blue tones), High Contrast
- [ ] Theme selector in Preferences
- [ ] Apply theme to all UI components (NSPanel, NSTableView, synthesis area)

### 4.3 Distribution & Licensing

**Tasks:**
- [ ] Set up LemonSqueezy product page ($24.99 one-time)
- [ ] Implement license activation flow (online validation → offline storage)
- [ ] Build landing page (features, pricing, screenshots, "How to set up your own API key" guide)
- [ ] py2app build with bundled model, codesign, notarize
- [ ] Test full install → activate → search flow on a clean Mac
- [ ] Write release notes

---

## Dependency Changes (v2 → v3)

### New dependencies
```
sentence-transformers    # local embeddings (nomic-embed-text)
keyring                  # Apple Keychain integration
anthropic                # Claude API (optional, Pro)
google-generativeai      # Gemini API (optional, Pro)
scikit-learn             # K-means for topic map (Pro)
umap-learn               # 2D projection for topic map (Pro)
```

### Removed dependencies (if going fully local by default)
```
# openai is kept but becomes optional (BYOK only)
```

### py2app bundle size estimate
```
Current app:              ~50 MB
+ nomic-embed-text-v1.5:  ~274 MB
+ sentence-transformers:   ~100 MB (torch, tokenizers, etc.)
+ other new deps:          ~20 MB
─────────────────────────────────────
Estimated total:           ~450 MB
```

This is within normal range for ML-powered Mac apps (Whisper Transcription is ~500 MB, Raycast is ~200 MB).

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Apple Foundation Models PyObjC bridge doesn't work cleanly | Blocks on-device synthesis | Medium | Fallback: bundled Swift CLI tool, or skip synthesis on free tier |
| nomic-embed-text quality noticeably worse than OpenAI for user's specific notes | Degraded free tier experience | Low | Quality testing on real queries; offer "Try Pro for better search" prompt |
| sentence-transformers + torch bloats app beyond 500 MB | User download friction | Medium | Use ONNX runtime instead of PyTorch (~50 MB vs ~300 MB) |
| LemonSqueezy / licensing issues | Can't monetize | Low | Paddle and Gumroad as backup vendors |
| macOS 26 adoption slow → Foundation Models reach is limited | Small free-tier synthesis audience | Medium | Groq free tier as alternative (no macOS 26 requirement) |
