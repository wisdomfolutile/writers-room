# Performance Plan — Search Latency

_Written 2026-06-10. All numbers measured on the real index (10,829 notes, 63MB embeddings, 17MB metadata) on this machine, not estimated._

## Goal

Make every search mode perform as advertised. Target: results render well under 1 second for
semantic/hybrid (network-bound floor), effectively instant (<150ms) for keyword.

## Measured baseline — where the time actually goes

### Mac app (Swift, per query)

| Operation | Current | After fix | Where |
|---|---|---|---|
| Keyword scoring (keyword + hybrid modes) | **2.10 s** | **0.04 s** (0.01 s parallel) | `NativeSearchEngine.keywordScore` |
| Temporal date parsing (temporal queries) | 0.23 s | ~0 (precomputed) | `QueryParser.parseNoteDate` via `applyTemporalFilter` |
| Short-note penalty | 0.02 s | ~0 (precomputed) | `applyShortNotePenalty` |
| Embedding API round-trip | 0.3–0.6 s | unchanged (floor); −0.1–0.3 s on first search via pre-warm | `callEmbeddingAPI` |
| Debounce before search fires | 0.4 s (semantic/hybrid) | 0.25–0.3 s | `SearchMode.debounceNanoseconds` |
| Synthesis prompt size | 8 × 3,000 chars (~6–7K tokens) | ~2.5K tokens → faster first token, ~60% cheaper | `NativeSynthesisEngine` |
| Semantic matrix math | already optimal (pre-normalized + BLAS sgemv) | — | `NativeEmbeddingStore` |

**The smoking gun is keyword scoring.** `keywordScore` lowercases the full content of every
note and runs Unicode-aware `String.contains` over ~17MB of text on *every* search. Keyword
mode (and hybrid, which also runs it) pays ~2.1 seconds of pure CPU per query. Verified fix:
precompute lowercased UTF-8 byte arrays once at index load (+0.3 s load time, one time), match
with byte-level scanning. Benchmarked on the real index with identical output scores
(checksum 3557.893 both ways): **2.095 s → 0.044 s** single-threaded, **0.0095 s** with
`concurrentPerform` across 8 cores.

### MCP server (Python, per query)

| Operation | Current | After fix |
|---|---|---|
| Cosine similarity (re-normalizes 63MB matrix every call) | 18 ms | 1.4 ms (pre-normalize at load) |
| Keyword scoring loop | 89 ms | 52 ms (precompute lowercase) |
| Temporal date parse loop | 39 ms | ~0 (precompute) |
| First-search index load (lazy) | +150 ms | 0 (preload at startup) |
| Top-n sort (`argsort` full sort) | 0.6 ms | 0.05 ms (`argpartition`) |
| Query embedding cache | none (every call hits API) | LRU like `searcher.py` |

The Python matcher was never the problem — the embedding API call dominates. But the MCP
server is missing the LRU embedding cache that `searcher.py` already has, and lazily loads
the index on first search.

## The plan

### Phase 1 — Mac app hot path (the 2-second win)

1. **Precompute search-ready forms in `NativeEmbeddingStore.load()`**, stored in parallel
   arrays alongside `metadata` (same index, same invariant as embeddings ↔ metadata):
   - `textLowerUTF8: [[UInt8]]` — lowercased `title + " " + content` bytes
   - `titleLowerUTF8: [[UInt8]]`
   - `contentLength: [Int]` — trimmed character count (for short-note penalty)
   - `noteYearMonth: [(year: Int, month: Int)?]` — parsed once with cached formatters
   - `folderLower: [String]`
   - Adds ~0.5 s to load (off the critical path, happens once at launch) and ~35MB RAM.
2. **Rewrite `keywordScore` to byte-level matching** over the precomputed arrays;
   parallelize the scoring loop with `DispatchQueue.concurrentPerform`. Scores must be
   bit-identical to today (the benchmark harness already proves this).
3. **Rewrite `applyTemporalFilter`, `applyShortNotePenalty`, `applyExcludedFolders`,
   `applyFolderFilter`, `applySourceFilter`** to read the precomputed arrays. This also
   removes the `parseNoteDate` formatter-mutation quirk (it reassigns `dateFormat` and does
   an O(n) `firstIndex(of:)` on every call).
4. **Precompute `availableSourceSlugs` and known-folder sets** at load/reload instead of
   per search.
5. Clean up the dead `vDSP_svesq` call in `normalizeRows` (computes a sum then discards it).

**Expected:** keyword mode ~2.2 s → <100 ms (feels instant; it makes no network call).
Hybrid loses the same 2.1 s. Temporal queries lose another ~0.25 s.

### Phase 2 — Network latency (the perceived-speed win)

6. **Pre-warm the API connection when the panel opens.** Fire a no-op request (HEAD or
   1-token ping) to the embedding endpoint so DNS + TCP + TLS complete while the user is
   still typing. Saves 100–300 ms on the first search of a session.
7. **Overlap work with the embedding call.** In hybrid mode, compute keyword scores
   concurrently with the embedding request (`async let`). When HyDE is on, start the raw
   query embedding *during* HyDE generation, not after (saves a full embed round-trip).
8. **Trim the synthesis prompt.** Currently 8 results × 3,000 chars (~6–7K tokens). Use top
   3 at 2,000 chars + remaining 5 at 800 (~2.5K tokens). Faster time-to-first-token and
   ~60% cheaper, with negligible quality loss — synthesis is 2–4 sentences.
9. **Cache the Keychain API key in memory** (invalidate on settings change). It's read twice
   per search (`performSearch` + `startSynthesis`) on the main actor today.
10. **Tune debounce:** semantic/hybrid 400 ms → 280 ms. Keep 150 ms for keyword. Enter
    already bypasses the debounce via `openSelected()` — leave that.

**Expected:** semantic search time-to-results ~0.8–1.0 s → ~0.5–0.7 s; synthesis text starts
appearing ~0.5–1 s sooner.

### Phase 3 — MCP server parity (`server.py`)

11. **Pre-normalize embeddings at load** (then similarity = single matvec). 18 ms → 1.4 ms.
12. **Preload the index at startup** in `main()` instead of lazily on first search.
13. **Add the LRU query-embedding cache** (port from `searcher.py`).
14. **Precompute lowercased text + (year, month) per note at load** for keyword/temporal.
15. **`argpartition` instead of full `argsort`** for top-n.
16. In hybrid mode, run keyword scoring in a thread while the embedding call is in flight.

Apply 11/14/15 to `searcher.py` too — it shares the logic and still backs the topic map and
any Python-side tooling.

### Phase 4 — Instrumentation (keep it fast)

17. **Add `os_signpost` timing around each search stage** in the app (parse → embed →
    score → filter → render; synthesis TTFT) and a debug-log line per search with the
    breakdown. The 2-second keyword regression survived because nothing measured per-stage
    latency. One log line per search makes the next regression visible immediately.

## What this does NOT change

- Scoring behavior. Every fix is a faster implementation of the same math — the byte-level
  keyword rewrite was verified score-identical on the real index.
- The `embeddings[i] ↔ metadata[i]` invariant. Precomputed arrays are built in the same load
  pass and live/die with the metadata array.
- The ~300–500 ms embedding API floor for semantic search. Going below that means local
  embeddings — that's the deferred Apple FM branch, out of scope here.

## Expected end state by mode

| Mode | Today (typical) | After |
|---|---|---|
| Keyword | ~2.3 s | **<150 ms** |
| Hybrid | ~2.7–3.2 s | **~0.5–0.8 s** |
| Semantic | ~0.8–1.1 s | **~0.5–0.7 s** |
| Temporal variants | +0.25 s on top | +~0 |
| Synthesis first text | ~1.5–2.5 s after results | **~0.8–1.2 s** |
| MCP first search | +150 ms cold | preloaded |

## Sequencing

Phase 1 alone delivers the advertised feel and is pure Swift with a benchmark harness already
proven — do it first, on a `feature/search-performance` branch in the Swift repo. Phase 2 is
independent and can follow immediately. Phase 3 mirrors into the Python repo on its own
branch. Phase 4 lands with Phase 1 so improvements are measured, not assumed.
