# Writers Room

A local semantic search tool over your Apple Notes library. Notes are read via AppleScript, embedded with OpenAI, and exposed to Claude Code as MCP tools — no database, no server infrastructure, everything runs locally on macOS.

## What it does

- Reads all your Apple Notes (folder by folder, skipping locked notes)
- Embeds them with OpenAI's `text-embedding-3-small`
- Lets you search semantically, by keyword, or with a hybrid blend — directly from Claude Code

## Requirements

- macOS (AppleScript is required — no cross-platform support)
- Python 3.10+
- [Claude Code](https://claude.ai/code) installed
- OpenAI API key

## Setup

```bash
git clone https://github.com/your-username/writers-room.git ~/claude-writers-room
cd ~/claude-writers-room

pip install -r requirements.txt

# Add your OpenAI API key
cp .env.example .env
# Edit .env and replace sk-... with your actual key

# Build the index (reads all your notes and embeds them)
# First run takes a while depending on how many notes you have
python3 indexer.py

# Register as an MCP server with Claude Code (one-time, user-scoped)
claude mcp add -s user writers-room -- python3 ~/claude-writers-room/server.py
```

Verify it's registered:
```bash
claude mcp list
```

## Indexer commands

```bash
python3 indexer.py                          # incremental update (only new/changed notes)
python3 indexer.py --force                  # re-embed everything from scratch
python3 indexer.py --folders "Ideas,Poems"  # index specific folders only
python3 indexer.py --list-folders           # list all folders with note counts
```

After re-indexing, call the `reload_index` tool in Claude Code to pick up changes without restarting.

## MCP tools (available in Claude Code)

| Tool | Description |
|---|---|
| `search_notes(query, n_results, mode)` | Search your notes |
| `index_status()` | Note count and per-folder breakdown |
| `reload_index()` | Reload index from disk after re-indexing |

### Search modes

| Mode | How it works |
|---|---|
| `semantic` (default) | OpenAI embedding → cosine similarity — best for vague or thematic queries |
| `keyword` | Exact phrase/word match — no API call, instant |
| `hybrid` | 50/50 blend of semantic + keyword scores |

## Architecture

```
Apple Notes (macOS app)
        │
        │  AppleScript (osascript)
        ▼
notes_reader.py    ← reads notes, folder-by-folder
        │
        ▼
indexer.py         ← embeds with OpenAI, saves to disk (incremental)
        │
        ▼
index/
  embeddings.npy   ← float32 array (N, 1536)
  metadata.json    ← note content + metadata
        │
        ▼
server.py          ← MCP server over stdio
        │
        ▼
Claude Code
```

## Privacy

Your notes never leave your machine except for the embedding API call to OpenAI (text only, no storage). The `index/` directory contains your note content and is excluded from this repo via `.gitignore` — never commit it.

## License

MIT
