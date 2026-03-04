# Writers Room — Developer Guide

A local semantic search tool over a personal Apple Notes library. Notes are read via AppleScript, embedded with OpenAI, and exposed to Claude Code as MCP tools. No database, no server infrastructure — everything runs locally on macOS.

---

## Architecture at a Glance

```
Apple Notes (macOS app)
        │
        │  AppleScript (osascript)
        ▼
notes_reader.py          ← reads notes, folder-by-folder, batch per folder
        │
        │  list of note dicts
        ▼
indexer.py               ← embeds with OpenAI, saves to disk (incremental)
        │
        │  writes
        ▼
index/
  embeddings.npy         ← float32 array, shape (N, 1536)
  metadata.json          ← list of N note dicts (full content included)
        │
        │  loaded into memory
        ▼
server.py                ← MCP server, exposes search_notes / index_status / reload_index
        │
        │  stdio (MCP protocol)
        ▼
Claude Code
```

The index is the source of truth for search. `metadata.json` stores full note content — no secondary lookup needed at query time.

---

## File Reference

### `notes_reader.py`
Reads notes from Apple Notes via AppleScript. The only file that touches the macOS Notes app.

**Key function:** `read_notes(folders=None, verbose=False) → list[dict]`
- Reads one folder at a time via `_read_single_folder()`
- Each folder = one AppleScript invocation, one osascript subprocess
- Folders that fail (locked, auth errors, iCloud sync issues) are silently skipped and returned as empty — no exception raised
- Returns note dicts with: `id`, `folder`, `title`, `modified`, `created`, `content`

**Key function:** `get_folder_names() → list[str]`
- Fast folder list without reading note content
- Used by `indexer.py` to enumerate all folders before indexing

**Critical AppleScript constraints:**

1. **Batch access requires inline specifiers.** The filter `whose password protected is false` must appear inline in each property access, not stored in a variable first. Storing it in a variable loses the "live specifier" and breaks batch access, forcing O(N) round-trips instead of O(1).

   ```applescript
   -- ✅ works (inline specifier each time)
   set noteTitles to name of (every note of aFolder whose password protected is false)
   set noteBodies to body of (every note of aFolder whose password protected is false)

   -- ❌ breaks batch access
   set theNotes to every note of aFolder whose password protected is false
   set noteTitles to name of theNotes  -- forces per-note round-trips
   ```

2. **`id` is not batchable.** Apple Notes' AppleScript dictionary does not support batch access for the `id` property. Synthetic IDs are built in Python instead: `f"{folder}||{title}||{created}"`. This is stable across reads as long as the title and creation date don't change.

3. **Notes are written to a temp file.** Large bodies would cause O(N²) string concatenation if built up in AppleScript memory. The script writes each note record directly to a temp file using `open for access`.

**Field separator:** `~~WRROOM~~` between fields, `~~NOTEEND~~` between notes. Chosen to be unlikely to appear in note content.

**HTML → text:** Note bodies come from Notes as HTML. `html_to_text()` uses BeautifulSoup with `html.parser` (stdlib, no extra binary). The result is stored in `content`.

---

### `indexer.py`
Builds and updates the local vector index. Designed to be resumable and incremental.

**Usage:**
```bash
python3 indexer.py                          # incremental update (all folders)
python3 indexer.py --force                  # re-embed everything from scratch
python3 indexer.py --folders "Ideas,Poems"  # only index specific folders
python3 indexer.py --list-folders           # show all folders with indexed counts
```

**How incremental updates work:**
- Loads existing index at start
- For each note: checks `note_id` (synthetic) + `modified` timestamp against existing index
- If both match → reuses existing embedding (no API call)
- If new or modified → re-embeds
- Saves after each folder — if the process crashes mid-run, progress is preserved

**What gets embedded:**
```python
f"Title: {note['title']}\nFolder: {note['folder']}\n\n{note['content']}"
```
Title and folder are included to give the embedding richer context. Content is truncated to 24,000 characters (~6k tokens) to stay comfortably under OpenAI's 8,192 token limit for `text-embedding-3-small`.

**Batch size:** 100 notes per OpenAI API call (the API maximum).

**Index files are replaced atomically per folder** — the folder's old entries are removed from the index and new ones appended. This means a partial run produces a valid (though incomplete) index, never a corrupt one.

---

### `server.py`
The MCP server. Exposes three tools to Claude Code over stdio.

**Tools:**

| Tool | Description |
|---|---|
| `search_notes(query, n_results, mode)` | Search notes. Returns full content. |
| `index_status()` | Note count and per-folder breakdown. |
| `reload_index()` | Force reload from disk after re-indexing. |

**Search modes:**

| Mode | How it works | When to use |
|---|---|---|
| `semantic` (default) | OpenAI embedding → cosine similarity | Vague, thematic, feeling-based queries |
| `keyword` | Exact phrase/word substring match | User remembers specific wording; no API call |
| `hybrid` | 50/50 blend of normalised semantic + keyword scores | Best general coverage |

**Keyword scoring logic:**
- Exact phrase match in `title + content` → score `1.0`
- Partial: fraction of query words found as substrings → score in `[0, 1]`
- Note: substring match (not word-boundary), so short query words like "of", "my" will match inside other words. Reliable for distinctive phrases; less precise for common words.

**In-memory cache:** The index is loaded once on the first tool call and held in `_embeddings` / `_metadata` globals. Call `reload_index` after re-running `indexer.py` to pick up new notes without restarting.

**Search result output** includes a `🔍 Find in Notes:` line per result — a search hint the user can paste into Apple Notes to locate the note directly. Uses the note title if distinctive; falls back to first 6 words of content for generic titles (e.g. "New Recording 18.m4a").

---

### `index/`

| File | Description |
|---|---|
| `embeddings.npy` | `float32` numpy array, shape `(N, 1536)` — one row per note |
| `metadata.json` | JSON array of N note dicts, same order as `embeddings.npy` |

**Note dict schema:**
```json
{
  "id": "FolderName||Note Title||Monday, 1 January 2024 at 00:00:00",
  "folder": "FolderName",
  "title": "Note Title",
  "modified": "Monday, 1 January 2024 at 00:00:00",
  "created": "Monday, 1 January 2024 at 00:00:00",
  "content": "Plaintext note body (HTML stripped, up to 24,000 chars)"
}
```

`embeddings[i]` corresponds to `metadata[i]`. This ordering is maintained by `indexer.py`. Do not sort or reorder `metadata.json` without regenerating `embeddings.npy`.

---

## Setup

**Prerequisites:** macOS, Python 3.14+, Apple Notes app, OpenAI API key.

```bash
cd ~/claude-writers-room
pip install -r requirements.txt

# Create .env
echo "OPENAI_API_KEY=sk-..." > .env

# Build the index (first run takes a while — ~5,800 notes)
python3 indexer.py

# Register with Claude Code (user-scoped, persists across projects)
claude mcp add -s user writers-room -- python3 ~/claude-writers-room/server.py
```

**Verify registration:**
```bash
claude mcp list
```

**After re-indexing**, trigger a reload in Claude Code by calling the `reload_index` tool, or restart Claude Code to pick up changes.

---

## Known Constraints & Gotchas

**macOS only.** The entire pipeline depends on `osascript`. There is no cross-platform equivalent.

**AppleScript is slow for large folders.** A folder with 500+ notes can take 30–60 seconds to read. This is a Notes/AppleScript limitation, not a code issue. The per-folder approach ensures other folders aren't blocked.

**Locked notes are silently skipped.** The `whose password protected is false` filter excludes them at the AppleScript level. They will never appear in search results.

**Keyword search has no word-boundary awareness.** Querying "sin" will match "single", "sinister", "basin". For precise phrase search, use longer, distinctive phrases.

**Hybrid mode is 50/50 fixed.** The weighting between semantic and keyword scores is not configurable via the tool interface. Change the constants in `call_tool()` in `server.py` if a different balance is needed.

**The index is not real-time.** Notes added or edited after the last `python3 indexer.py` run will not appear in search until re-indexed.

**Content is truncated at 24,000 characters for embedding.** Very long notes (rare) will have their embedding computed on the first 24k chars only. Full content is still stored in `metadata.json` and returned in search results.

---

## Planned Work

- **macOS menu bar app** using `rumps` (Python). Planned features:
  - Search field in dropdown, results shown inline (no browser or terminal)
  - Clickable footnote per result that opens the note directly in Apple Notes
  - AppleScript: `tell app "Notes" to show note named "..." in folder "..."`
  - Or via URL scheme: `notes://` (reliability TBD — investigate before building)
