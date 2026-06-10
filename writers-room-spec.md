# Writers Room — Product Spec Sheet

## Overview

Writers Room is a native macOS semantic search engine for personal notes with AI synthesis. It reads from Apple Notes (and other sources), embeds content with AI, and lets you search by meaning — not just keywords. Everything runs locally. No cloud servers, no accounts, no data leaves your Mac beyond API calls to your chosen provider.

**Bundle ID:** `com.writersroom.app`
**Platform:** macOS 26+
**Version:** 3.0 (stable on `main`, tagged `v3.0-stable`)

---

## What It Does

### Core Search
- **Semantic Search** — Find notes by meaning and theme ("what have I written about grief"), not just keywords. Uses OpenAI `text-embedding-3-small` embeddings + cosine similarity.
- **Keyword Search** — Instant literal phrase matching. No API call, zero latency.
- **Hybrid Search** — 50/50 blend of semantic + keyword scoring for balanced coverage.
- **HyDE Deep Search** — Hypothetical document expansion; the query is "imagined" into a full paragraph before retrieval, improving recall on vague prompts.
- **URL-Aware Search** — Paste a literary magazine submission call or any webpage. Writers Room reads it, extracts themes, and surfaces matching drafts automatically.

### AI Synthesis (Second-Brain Companion)
Before search results load, the chosen LLM streams a warm, conversational summary: *"You've been circling this idea since 2022…"* with clickable `[[Note Title]]` references that open the source note in Apple Notes.

### Mind Constellation
A full-window interactive visualization of your entire note library. UMAP + K-means clusters notes into thematic neighborhoods on a 2D map. Click any cluster to zoom in and read notes within that topic. Built with Metal + SpriteKit, with SwiftUI liquid glass overlays (macOS 26).

Features:
- Pan, zoom, click clusters to drill down
- Time-lapse scrub bar across your writing history
- **Mind Profile** — AI-generated summary of your thinking patterns, presented as a liquid glass notification → expandable card
- Walkthrough tips for first-time users
- Native macOS fullscreen support

### On This Day
Surfaces old notes from the same calendar date, years prior. Rediscovery and nostalgia built in.

---

## Tech Stack

### Python Backend (`~/claude-writers-room/`)

| Component | Technology |
|---|---|
| Embedding | OpenAI `text-embedding-3-small` (1536 dim) — BYOK: Voyage AI, Gemini, Mistral, Cohere, Jina |
| Synthesis | GPT-4o-mini streaming — BYOK: Claude, Gemini, Groq, DeepSeek, Mistral, OpenRouter |
| Vector Index | NumPy flat binary (`embeddings.npy`) + JSON metadata — in-memory at runtime |
| Note Reading | AppleScript (osascript) + BeautifulSoup HTML→text |
| Multi-Source | Apple Notes (primary), Obsidian (.md), Bear (SQLite), generic markdown folders |
| IPC | JSON-line over stdin/stdout (`bridge.py`) for Swift ↔ Python |
| MCP Server | `server.py` — exposes `search_notes`, `index_status`, `reload_index` to Claude Code |
| Key Storage | Apple Keychain via `keyring` library |

### Swift Frontend (`~/WritersRoom/`)

| Component | Technology |
|---|---|
| UI Framework | SwiftUI + AppKit (hybrid) |
| Concurrency | Swift 6.0, async/await |
| Visualization | Metal + SpriteKit (constellation), SwiftUI liquid glass overlays |
| Global Hotkey | KeyboardShortcuts library (Cmd+Shift+Space) |
| State | @Observable (Swift 6) + UserDefaults |
| Build | Xcode, py2app for Python bundling |

### Landing Page

Astro 4.x + TypeScript + Tailwind CSS. Animated typewriter hero, feature grid, provider showcase, pricing section.

---

## Architecture

```
Apple Notes / Obsidian / Bear / Markdown
        │
        │  AppleScript / file readers
        ▼
notes_reader.py + source adapters
        │
        ▼
indexer.py (incremental, resumable, saves per-folder)
        │
        ▼
index/embeddings.npy  (float32, N × 1536)
index/metadata.json   (N note dicts with full content)
        │
        ├──→ bridge.py ──→ Swift app (menu bar search + synthesis)
        │
        └──→ server.py ──→ Claude Code (MCP tools over stdio)
```

---

## UI / UX

### Menu Bar App
- **Cmd+Shift+Space** global hotkey opens floating search panel
- Frosted glass NSPanel (~620×516px), dark/light mode aware
- Synthesis area (~130px): LLM streams answer with `[[Note Title]]` clickable links
- Results table: title, snippet, folder, relevance score, "Open in Notes" button
- Slash commands: `/sm` (semantic), `/hy` (hybrid), `/ky` (keyword)
- ESC closes, Enter opens first result

### Settings (Tabbed)
1. **General** — Default search mode, synthesis provider picker
2. **Search** — Depth slider (Surface ↔ Deep), result count
3. **Sources** — Enable/disable note sources, Obsidian vault paths
4. **Indexing** — Re-index button, progress bar, per-folder status
5. **Shortcuts** — Global hotkey customization

### Menu Bar Menu
- "Search Notes" (Cmd+Shift+Space)
- "{N} notes indexed" badge
- "Re-index Notes"
- "Mind Constellation"
- "Preferences…" (Cmd+,)
- "Quit Writers Room" (Cmd+Q)

---

## Pricing

| Tier | Price | Notes Limit | Key Features |
|---|---|---|---|
| **Free** | $0 | 1,000 | Semantic/keyword/hybrid search, AI synthesis (on-device or free Groq tier), menu bar access |
| **Pro** | $24.99 one-time | Unlimited | BYOK multi-provider, HyDE deep search, URL-aware search, Mind Constellation, daily digest, export, smart folders |

### API Cost to User (at 50 searches/day with GPT-4o-mini)

| Period | Cost |
|---|---|
| Per search | ~$0.00028 |
| Per day | ~$0.014 |
| Per month | ~$0.43 |
| Per year | ~$5.20 |

---

## BYOK Provider Support

### Synthesis Providers

| Provider | Model | Input $/1M | Output $/1M |
|---|---|---|---|
| OpenAI | GPT-4o-mini | $0.15 | $0.60 |
| Google | Gemini 2.5 Flash Lite | $0.10 | $0.40 |
| Anthropic | Claude Haiku 4.5 | $1.00 | $5.00 |
| Groq | Llama 3.1 8B | $0.05 | $0.08 |
| Mistral | Mistral Small 4 | $0.15 | $0.60 |
| DeepSeek | V3.2 | $0.28 | $0.42 |
| OpenRouter | 500+ models | Varies | Varies |

### Embedding Providers

| Provider | Model | Cost/1M tokens | Quality (MTEB) |
|---|---|---|---|
| Gemini | Embedding 001 | $0.15 | 68.3 (best) |
| Voyage AI | voyage-3.5 | $0.06 | ~65 |
| OpenAI | text-embedding-3-small | $0.02 | 62.3 |
| Mistral | mistral-embed | $0.01 | 55.3 |

Implementation uses OpenAI SDK's `base_url` parameter for most providers (zero new dependencies).

---

## Index Stats (Current)

- **5,844 notes** indexed across **88 folders**
- 2 folders skipped (auth errors): "2018", "FREELANCE"
- Embedding dimensions: 1,536
- Index files: ~50MB total (embeddings.npy + metadata.json)
- Search latency: **~86ms** (vs ~1.7s native macOS search — 20x faster)

---

## Key Files

### Python Backend
| File | Purpose |
|---|---|
| `notes_reader.py` | AppleScript reader — per-folder batch access, skips locked notes |
| `indexer.py` | Incremental embedding + index build (resumable, saves per-folder) |
| `searcher.py` | In-memory search engine (cosine similarity + keyword scoring) |
| `server.py` | MCP server for Claude Code integration |
| `bridge.py` | Swift ↔ Python JSON-line IPC |
| `synthesizer.py` | LLM streaming synthesis |
| `providers.py` | Multi-provider BYOK registry & client factory |
| `topic_map.py` | UMAP + K-means clustering for Mind Constellation |
| `preferences.py` | Settings persistence |
| `source_config.py` | Multi-source adapter loader |

### Swift Frontend
| File | Purpose |
|---|---|
| `WritersRoomApp.swift` | App entry, menu bar definition |
| `AppDelegate.swift` | Lifecycle, bridge subprocess launch |
| `AppState.swift` | Observable app state |
| `SearchViewModel.swift` | Search logic, result binding |
| `FloatingPanel.swift` | Floating search panel |
| `SettingsView.swift` | Tabbed preferences |
| `ConstellationWindow.swift` | Mind Constellation window + SwiftUI overlay management |
| `ConstellationScene.swift` | SpriteKit visualization (Metal-backed) |
| `MindProfileOverlay.swift` | Liquid glass Mind Profile (notification → card → pill) |
| `ConstellationControlsOverlay.swift` | Liquid glass help + back buttons |

---

## Roadmap

| Priority | Feature | Branch | Status |
|---|---|---|---|
| 1 | BYOK multi-provider (synthesis + embeddings) | `feature/byok-providers` | In progress |
| 2 | Apple Foundation Models (on-device, zero-API default) | `feature/apple-fm` | Deferred (macOS 26+ only) |
| 3 | Smart folders / saved searches | TBD | Planned |
| 4 | Daily digest email | TBD | Planned |
| 5 | Export (Markdown, PDF) | TBD | Planned |
| 6 | Custom themes | TBD | Planned |

**Merge order:** BYOK first (additive, backward-compatible), then Apple FM (changes defaults).

---

## Example Queries

- "poems about my mother's kitchen"
- "what have I written about leaving home?"
- "that startup idea from last summer"
- "reflections on faith and doubt"
- "the essay about Lagos traffic"
- "notes where I mentioned Soyinka"
- "what was I thinking in December 2023?"
- [Paste a literary magazine submission URL]

---

## Value Propositions

1. **Deeper Recall** — Search "what have I been avoiding writing about" and get an answer.
2. **Reads Your Intent** — Type a name, it searches literally. Ask a question, it searches by meaning.
3. **Paste a Link, Find a Match** — Drop in a submission call. It reads the page and surfaces your best-fit drafts.
4. **A Conversation with Your Past Self** — Before results load, get a warm summary with clickable links to source notes.
5. **See What You Think About** — Visual map of every note clustered by theme.
6. **Your Notes Stay Yours** — Everything runs on your Mac. No cloud, no accounts, no servers.

---

## Constraints

- **macOS only** — AppleScript is the foundation
- **Not real-time** — Index must be rebuilt after note changes
- **Locked notes excluded** — Password-protected notes never appear
- **Content truncated at 24K chars** for embedding (full content still in search results)
- **Hybrid search is 50/50 fixed** — not user-configurable via UI
