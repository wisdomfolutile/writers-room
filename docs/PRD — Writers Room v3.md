# Product Requirements Document — Writers Room v3 (Commercial Release)

**Author:** Wisdom Deji-Folutile
**Date:** March 18, 2026
**Status:** Draft

---

## 1. Product Vision

Writers Room is a local-first semantic search companion for Apple Notes. v3 transforms it from a personal tool into a commercial Mac app with a free tier (fully functional, on-device AI) and a Pro tier ($24.99 one-time) that unlocks BYOK multi-provider AI, advanced search, and power features.

**Core principle:** The free tier must be genuinely useful — not a crippled demo. The Pro tier sells itself by being noticeably better for heavy users.

---

## 2. Target Users

| Persona | Description | Tier |
|---|---|---|
| **Casual noter** | 200-800 notes, searches occasionally, wants it to "just work" | Free |
| **Prolific writer** | 1,000-10,000+ notes, searches daily, cares about quality | Pro |
| **Power user / developer** | Wants to choose their own AI provider, customize everything | Pro |

---

## 3. Tier Structure

### Free Tier
- Semantic search (local embeddings via nomic-embed-text-v1.5)
- AI synthesis (Apple Foundation Models, on-device)
- Keyword + hybrid search modes
- Up to **1,000 notes** indexed
- All UI features (floating panel, keyboard navigation, ESC close, etc.)

### Pro Tier — $24.99 one-time
- **Unlimited notes** indexed
- **BYOK multi-provider synthesis** — OpenAI, Groq, Mistral, DeepSeek, Together, OpenRouter, Ollama, + Anthropic/Google with native SDKs
- **BYOK multi-provider embeddings** — OpenAI, Google Gemini, Voyage AI, Cohere, Mistral, Jina
- **HyDE deep search** — hypothetical document expansion for better semantic recall
- **URL search** — search web content alongside notes
- **Smart folders & saved searches** — pin recurring queries, auto-refresh
- **Daily digest / "On This Day"** — resurface forgotten notes by date
- **Export** — search results to Markdown / PDF
- **Custom themes** — visual personalization
- **Topic map** — K-means cluster visualization of your notes

---

## 4. Functional Requirements

### 4.1 Local-First AI (Free Tier)

| Req ID | Requirement | Priority |
|---|---|---|
| F-001 | Bundle nomic-embed-text-v1.5 (~274 MB) for local embedding | P0 |
| F-002 | Integrate Apple Foundation Models framework for on-device synthesis (macOS 26+) | P0 |
| F-003 | Fallback: if macOS < 26, disable synthesis (show results only, no AI summary) | P0 |
| F-004 | Local indexing must work without any API key | P0 |
| F-005 | Index cap enforcement: stop indexing at 1,000 notes on free tier, show upgrade prompt | P0 |
| F-006 | Re-index all notes when switching embedding providers (migration flow) | P1 |

### 4.2 BYOK Multi-Provider (Pro Tier)

| Req ID | Requirement | Priority |
|---|---|---|
| P-001 | Preferences pane: provider selector for synthesis (dropdown) | P0 |
| P-002 | Preferences pane: provider selector for embeddings (dropdown) | P0 |
| P-003 | Per-provider: API key field + optional custom endpoint URL | P0 |
| P-004 | "Test Connection" button per provider — validates key with a lightweight API call | P1 |
| P-005 | Store API keys in Apple Keychain via `keyring` library | P0 |
| P-006 | OpenAI SDK base_url pattern for: OpenAI, Groq, Mistral, DeepSeek, Together, Fireworks, OpenRouter, Ollama | P0 |
| P-007 | Native Anthropic SDK integration for Claude models | P1 |
| P-008 | Native Google SDK integration for Gemini models + Gemini Embedding 001 | P1 |
| P-009 | Provider config stored in `~/.writersroom/config.json` (not in Apple Keychain — only keys go there) | P0 |
| P-010 | Synthesis and embedding providers are independently selectable (mix and match) | P0 |

### 4.3 Pro Search Features

| Req ID | Requirement | Priority |
|---|---|---|
| S-001 | HyDE: generate hypothetical answer from query, embed that, search with expanded vector | P1 |
| S-002 | URL search: index web content alongside notes (already shipped) | P0 (done) |
| S-003 | Smart folders: save a query + mode + filters, auto-refresh on open | P2 |
| S-004 | "On This Day": surface notes created/modified on today's date in past years | P2 |

### 4.4 Pro Output Features

| Req ID | Requirement | Priority |
|---|---|---|
| O-001 | Export search results to Markdown (.md file) | P2 |
| O-002 | Export search results to PDF | P2 |
| O-003 | Custom themes: 3-5 built-in themes (dark, light, warm, cool, high-contrast) | P2 |

### 4.5 Topic Map (Pro)

| Req ID | Requirement | Priority |
|---|---|---|
| T-001 | K-means clustering on embedding vectors (configurable k, default auto via silhouette score) | P2 |
| T-002 | 2D visualization via t-SNE or UMAP dimensionality reduction | P2 |
| T-003 | Interactive: click cluster to see notes, click note to open in Apple Notes | P2 |
| T-004 | Auto-label clusters using most representative note titles or GPT summary | P3 |

### 4.6 Licensing & Gating

| Req ID | Requirement | Priority |
|---|---|---|
| L-001 | License key validation (offline-capable — see codebase strategy) | P0 |
| L-002 | Gated features check `is_pro()` before execution | P0 |
| L-003 | Upgrade prompts: contextual, non-intrusive (e.g., "Unlock unlimited notes — Upgrade to Pro") | P1 |
| L-004 | License stored locally in `~/.writersroom/license.json` | P0 |
| L-005 | Grace period: 7-day Pro trial on first install (no credit card) | P1 |

---

## 5. Non-Functional Requirements

| Req ID | Requirement |
|---|---|
| NF-001 | App size < 400 MB (including bundled nomic-embed model) |
| NF-002 | Search latency < 500ms for local embeddings, < 2s for cloud embeddings |
| NF-003 | Synthesis streaming must begin within 1s (local) or 3s (cloud) |
| NF-004 | No data leaves the machine unless user explicitly configures a cloud provider |
| NF-005 | All API keys stored in Apple Keychain, never in plaintext config files |
| NF-006 | Graceful degradation: if a cloud provider is unreachable, fall back to local or show error |
| NF-007 | macOS 15 (Sequoia) minimum for app launch; macOS 26+ for Apple Foundation Models |

---

## 6. Success Metrics

| Metric | Target |
|---|---|
| Free → Pro conversion rate | > 8% within 30 days of install |
| Daily active searches (Pro users) | > 10/day average |
| App Store rating | > 4.5 stars |
| Support tickets per 100 users | < 3/month |
| Time to first successful search (new user) | < 2 minutes |

---

## 7. Out of Scope (v3)

- iOS / iPadOS app (future — requires non-AppleScript note access)
- Real-time note sync (index remains manual/scheduled)
- Collaborative features
- Note editing / creation from within Writers Room
- Server-side infrastructure (everything stays local)
