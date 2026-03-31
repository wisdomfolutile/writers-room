# Writers Room — Python Backend

Semantic search over Apple Notes. Reads via AppleScript, embeds with OpenAI, exposes to Claude Code as MCP tools and to the Swift app via `bridge.py`. Everything local, macOS only.

## Architecture

```
Apple Notes → notes_reader.py (AppleScript) → indexer.py (OpenAI embeds)
  → index/embeddings.npy + metadata.json
  → server.py (MCP tools, stdio)      → Claude Code
  → bridge.py (JSON-line, stdin/stdout) → Swift app (~/WritersRoom/)
```

`metadata.json` stores full note content. `embeddings[i]` ↔ `metadata[i]` — never reorder one without the other.

## Critical: AppleScript Constraints

These are non-obvious and will break things if violated:

1. **Inline specifiers only.** `whose password protected is false` must appear inline per property access. Storing in a variable breaks batch access (O(N) instead of O(1)).
2. **`id` is not batchable.** Synthetic IDs: `f"{folder}||{title}||{created}"`.
3. **Temp file output.** AppleScript writes to temp file to avoid O(N^2) string concat.
4. **Separators:** `~~WRROOM~~` between fields, `~~NOTEEND~~` between notes.

## Key Files

| File | Role |
|---|---|
| `notes_reader.py` | AppleScript reader. Only file touching macOS Notes. Per-folder, skips locked notes. |
| `indexer.py` | Incremental embed + index. Saves per-folder (resumable). 24K char truncation. |
| `server.py` | MCP server: `search_notes(query, n_results, mode)`, `index_status()`, `reload_index()` |
| `bridge.py` | Swift ↔ Python JSON-line IPC. Long-running subprocess. |
| `searcher.py` | In-memory cosine similarity + keyword scoring |
| `synthesizer.py` | LLM streaming synthesis |
| `providers.py` | BYOK provider registry. Uses OpenAI SDK `base_url` pattern. |
| `topic_map.py` | UMAP + K-means clustering, mind profile, cross-cluster bridges |

## Search Modes

- **semantic** (default): OpenAI embedding → cosine similarity
- **keyword**: substring match, no API call. No word-boundary awareness ("sin" matches "single").
- **hybrid**: 50/50 normalized blend. Weighting hardcoded in `server.py`.

## Index

- ~5,844 notes, 88 folders. 2 skipped (auth errors: "2018", "FREELANCE").
- Files: `index/embeddings.npy` (float32, N×1536) + `index/metadata.json`
- Incremental: matches on `note_id` + `modified`. Unchanged notes reuse embeddings.
- Batch size: 100 notes/API call. Atomic replacement per folder.

## Setup

```bash
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
python3 indexer.py                    # first run indexes all
claude mcp add -s user writers-room -- python3 ~/claude-writers-room/server.py
```

After re-indexing: call `reload_index` tool or restart Claude Code.

## Branching

| Branch | Purpose | Status |
|---|---|---|
| `main` (tagged `v3.0-stable`) | Stable. Do not commit during feature work. | Frozen |
| `feature/byok-providers` | Multi-provider BYOK (synthesis + embeddings) | Active |
| `feature/apple-fm` | Apple Foundation Models on-device | Deferred |

Merge order: BYOK first → Apple FM rebases on it. Bug fixes: commit to `main`, cherry-pick.
Swift repo (`~/WritersRoom/`) mirrors same branches.

## Planned

- BYOK multi-provider: see `Writers Room — BYOK Multi-Provider Analysis.md`
- Apple FM on-device: see `Writers Room — Commercialization Analysis.md`
- Pro tier: $24.99 one-time, 1K free limit, topic map, daily digest, smart folders, export

## Content Exclusions

- **Moses** folder: contains writing by other authors, not the user's own work
