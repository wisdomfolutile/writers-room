# Product Roadmap — Writers Room v3

---

## Timeline Overview

```
        Apr 2026          May 2026          Jun 2026          Jul 2026
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  Phase 1     │  │  Phase 2     │  │  Phase 3     │  │  Phase 4     │
    │  Local-First │  │  BYOK Multi  │  │  Pro Search  │  │  Polish &    │
    │  Foundation  │  │  Provider    │  │  & Output    │  │  Launch      │
    └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
         Wk 1-3            Wk 4-6            Wk 7-9           Wk 10-12

    ▲ Alpha                ▲ Beta             ▲ RC              ▲ v3.0
    (local AI works)       (BYOK works)       (all features)    (public launch)
```

---

## Phase 1: Local-First Foundation
**Weeks 1-3 (April 2026)**

### Week 1 — Local Embeddings
| Task | Deliverable |
|---|---|
| Set up `local_embedder.py` with nomic-embed-text-v1.5 | Local embedding works in Python |
| Modify `indexer.py` to support `--provider local` | Can index notes without any API key |
| Handle dimension mismatch (1536→768) detection | Graceful migration prompt |
| Quality test: 20 queries, compare local vs OpenAI | Documented quality delta |

### Week 2 — On-Device Synthesis
| Task | Deliverable |
|---|---|
| Investigate Apple Foundation Models via PyObjC | Feasibility confirmed or fallback chosen |
| Implement `local_synthesizer.py` | Streaming synthesis from on-device model |
| Modify `synthesizer.py` to dispatch local vs cloud | Provider routing works |
| macOS version detection and graceful fallback | Works on macOS 15+ (synthesis disabled if < 26) |

### Week 3 — Feature Gating + Config
| Task | Deliverable |
|---|---|
| Create `license.py` with `is_pro()`, `note_limit()` | Tier checking works |
| Create `config.py` for centralized settings | Single config source |
| Wire note limit (1,000) into indexer | Free tier cap enforced |
| Implement 7-day trial auto-activation | New installs get Pro trial |
| Create `~/.writersroom/` directory structure | App data persists correctly |

**Phase 1 Milestone:** App works end-to-end with zero API keys. Search quality is acceptable. Free/Pro gating is in place.

---

## Phase 2: BYOK Multi-Provider
**Weeks 4-6 (May 2026)**

### Week 4 — Provider Abstraction
| Task | Deliverable |
|---|---|
| Create `providers.py` with full registry | All 10 synthesis + 7 embedding providers defined |
| Implement OpenAI SDK base_url pattern | Groq, Mistral, DeepSeek, etc. work with zero new deps |
| Implement Apple Keychain storage via `keyring` | API keys stored securely |
| Add Anthropic SDK integration | Claude models accessible |
| Add Google SDK integration | Gemini synthesis + Gemini Embedding 001 accessible |

### Week 5 — Preferences UI
| Task | Deliverable |
|---|---|
| Build Preferences NSPanel | Settings UI opens from menu bar |
| Provider dropdowns (synthesis + embeddings) | Users can select their provider |
| API key input with mask/reveal | Keys entered securely |
| "Test Connection" button | Validates key with lightweight API call |
| License status and activation UI | Users can enter license key |

### Week 6 — Re-indexing & Integration
| Task | Deliverable |
|---|---|
| Re-index flow when embedding provider changes | Background re-index with progress |
| Provider error handling (invalid key, rate limit, timeout) | Graceful error messages |
| End-to-end testing: all 10 synthesis providers | Verified working with real keys |
| End-to-end testing: all 7 embedding providers | Verified working with real keys |
| Config persistence across app restarts | Settings survive quit/relaunch |

**Phase 2 Milestone:** Pro users can choose any provider for synthesis and embeddings. Preferences UI is functional. All providers tested.

---

## Phase 3: Pro Search & Output
**Weeks 7-9 (June 2026)**

### Week 7 — HyDE + Smart Folders
| Task | Deliverable |
|---|---|
| Implement HyDE search pipeline | Hypothetical document generation → embedding → search |
| HyDE quality test: 20 vague queries, measure recall lift | Documented improvement |
| Smart folders data model + persistence | Saved searches work |
| Smart folders UI (save button, sidebar/dropdown) | Users can save and recall searches |

### Week 8 — "On This Day" + Export
| Task | Deliverable |
|---|---|
| "On This Day" date filtering and view | Notes surfaced by historical date |
| Markdown export | Search results → .md file |
| PDF export | Search results → .pdf file |
| Export button in results UI | File save dialog works |

### Week 9 — Testing & Hardening
| Task | Deliverable |
|---|---|
| Full test pass: all features, free + pro tiers | Bug list triaged |
| Performance profiling: search latency, memory usage | Meets NF requirements |
| Edge cases: empty results, very long notes, special characters | Robust handling |
| Upgrade prompt UX refinement | Non-intrusive, contextual prompts |

**Phase 3 Milestone:** All Pro search features work. Export is functional. App is stable.

---

## Phase 4: Visual Features & Launch
**Weeks 10-12 (July 2026)**

### Week 10 — Topic Map
| Task | Deliverable |
|---|---|
| K-means clustering on embeddings | Clusters computed |
| t-SNE/UMAP 2D projection | Coordinates for visualization |
| Interactive NSView rendering | Visual map with hover/click |
| Cluster auto-labeling | Meaningful cluster names |

### Week 11 — Themes + Distribution
| Task | Deliverable |
|---|---|
| Define 5 theme presets | Theme schema + color values |
| Theme selector in Preferences | Users can switch themes |
| Apply themes to all UI components | Consistent visual refresh |
| LemonSqueezy product page setup | Payment and licensing ready |
| py2app build with bundled model | .app package works |
| Codesign + notarize | Passes macOS Gatekeeper |

### Week 12 — Launch Prep
| Task | Deliverable |
|---|---|
| Landing page (features, pricing, screenshots) | Public-facing website |
| "How to get an API key" help page per provider | Support documentation |
| Clean Mac install test | Full flow: download → install → search |
| Release notes | Changelog for v3.0 |
| Soft launch to beta testers | Feedback collection |
| **Public launch** | **v3.0 released** |

**Phase 4 Milestone:** App is polished, distributed, and commercially available.

---

## Post-Launch Roadmap (v3.1+)

| Version | Features | Timeline |
|---|---|---|
| **v3.1** | Spotlight / Raycast integration, keyboard-first workflows (global hotkey) | Aug 2026 |
| **v3.2** | Multi-query synthesis ("love vs loss"), note relationship graph | Sep 2026 |
| **v3.3** | Scheduled auto-indexing (daily/hourly), notification on new notes | Oct 2026 |
| **v4.0** | iOS companion app (read-only search, iCloud sync of index) | Q1 2027 |

---

## Key Decisions Log

| Decision | Chosen | Rationale |
|---|---|---|
| Single codebase vs separate builds | Single + feature gate | 1x maintenance, zero drift risk |
| Subscription vs one-time purchase | $24.99 one-time | Solo-dev utility — subscriptions generate resentment |
| Default embedding model | nomic-embed-text-v1.5 | Best local quality (MTEB ~65), 8K context matches current setup |
| Default synthesis | Apple Foundation Models | Zero cost, zero latency, privacy-first |
| Multi-provider mechanism | OpenAI SDK base_url | Zero new deps for 80% of providers |
| License vendor | LemonSqueezy | One-time purchase support, license API, Mac-friendly |
| Free tier note limit | 1,000 | Natural conversion lever — power users hit it organically |
| Trial period | 7 days Pro | Let users experience the full product before deciding |

---

## Dependencies & Blockers

| Dependency | Status | Impact if delayed |
|---|---|---|
| macOS 26 beta (Foundation Models) | Available (WWDC 2025) | Can't test on-device synthesis until macOS 26 ships |
| nomic-embed-text-v1.5 availability | Available now | None |
| LemonSqueezy license API | Available now | None — Paddle/Gumroad as backup |
| Anthropic Python SDK | Available now | None |
| Google Generative AI SDK | Available now | None |
| ONNX Runtime (optional, for smaller app size) | Available now | Falls back to PyTorch (larger bundle) |
