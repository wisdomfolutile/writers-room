"""
Writers Room MCP Server

Exposes your Apple Notes index to Claude as searchable tools.

Tools:
    search_notes(query, n_results, mode)  — semantic, keyword, or hybrid search
    index_status()                        — show how many notes are indexed
"""

import asyncio
import json
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from openai import OpenAI

load_dotenv(Path(__file__).parent / ".env")

INDEX_DIR = Path(__file__).parent / "index"
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
METADATA_FILE = INDEX_DIR / "metadata.json"
EMBEDDING_MODEL = "text-embedding-3-small"

client = OpenAI()
server = Server("writers-room")

# In-memory cache — loaded once on first search
_embeddings: np.ndarray | None = None
_metadata: list[dict] | None = None


def load_index() -> tuple[np.ndarray, list[dict]]:
    global _embeddings, _metadata
    if _embeddings is None:
        if not EMBEDDINGS_FILE.exists():
            raise RuntimeError(
                "Index not found. Run: python3 indexer.py"
            )
        _embeddings = np.load(EMBEDDINGS_FILE)
        with open(METADATA_FILE) as f:
            _metadata = json.load(f)
    return _embeddings, _metadata


def reload_index() -> tuple[np.ndarray, list[dict]]:
    """Force reload from disk (useful after re-indexing)."""
    global _embeddings, _metadata
    _embeddings = None
    _metadata = None
    return load_index()


def cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    normed = matrix / norms
    return normed @ query_norm


def get_query_embedding(query: str) -> np.ndarray:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
    return np.array(response.data[0].embedding, dtype=np.float32)


def keyword_score(query: str, note: dict) -> float:
    text = (note["title"] + " " + note["content"]).lower()
    q = query.lower()

    # Exact phrase match
    if q in text:
        return 1.0

    # Partial: fraction of query words found
    words = q.split()
    hits = sum(1 for w in words if w in text)
    return hits / len(words) if words else 0.0


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_notes",
            description=(
                "Search through the user's Apple Notes. "
                "Supports three modes: 'semantic' (default) finds notes by meaning/theme/vibe; "
                "'keyword' finds notes containing exact phrases or words — use this when the user "
                "remembers specific wording; 'hybrid' combines both for best coverage. "
                "Returns full note content so you can reason over it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What to search for. Can be natural language, a theme, "
                            "a topic, an idea, a question, a vibe, or an exact phrase."
                        ),
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5, max: 20)",
                        "default": 5,
                    },
                    "mode": {
                        "type": "string",
                        "description": (
                            "Search mode: 'semantic' (default) — meaning-based; "
                            "'keyword' — exact phrase/word match, no API call; "
                            "'hybrid' — combines both scores 50/50."
                        ),
                        "enum": ["semantic", "keyword", "hybrid"],
                        "default": "semantic",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="index_status",
            description=(
                "Check how many Apple Notes are indexed in Writers Room, "
                "and see the breakdown by folder."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="reload_index",
            description=(
                "Reload the search index from disk. Use this after running "
                "python3 indexer.py to pick up newly indexed notes."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "search_notes":
        query = arguments["query"]
        n = min(int(arguments.get("n_results", 5)), 20)
        mode = arguments.get("mode", "semantic")

        embeddings, metadata = load_index()

        if mode == "keyword":
            kw_scores = np.array([keyword_score(query, note) for note in metadata])
            scores = kw_scores
        elif mode == "hybrid":
            query_vec = get_query_embedding(query)
            sem_scores = cosine_similarity(query_vec, embeddings)
            # Normalise semantic scores to [0, 1]
            s_min, s_max = sem_scores.min(), sem_scores.max()
            sem_norm = (sem_scores - s_min) / (s_max - s_min + 1e-10)
            kw_scores = np.array([keyword_score(query, note) for note in metadata])
            scores = 0.5 * sem_norm + 0.5 * kw_scores
        else:  # semantic (default)
            query_vec = get_query_embedding(query)
            scores = cosine_similarity(query_vec, embeddings)

        top_indices = np.argsort(scores)[::-1][:n]

        output_lines = [f"Found {n} notes for: '{query}'\n"]
        for rank, idx in enumerate(top_indices, 1):
            note = metadata[idx]
            score = float(scores[idx])
            # Build a search hint: use title if it's not a generic filename,
            # otherwise fall back to first 6 words of content
            title = note["title"].strip()
            is_generic = (
                not title
                or title.lower().startswith("new recording")
                or title.lower() in ("untitled", "untitled note")
            )
            if is_generic:
                first_words = " ".join(note["content"].split()[:6])
                search_hint = f'"{first_words}…"'
            else:
                search_hint = f'"{title}"'
            output_lines += [
                f"{'=' * 60}",
                f"[{rank}] {note['title']}",
                f"Folder: {note['folder']}  |  Modified: {note['modified']}  |  Relevance: {score:.3f}",
                f"🔍 Find in Notes: search {search_hint} (folder: {note['folder']})",
                "",
                note["content"],
                "",
            ]

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    elif name == "index_status":
        try:
            embeddings, metadata = load_index()
            folders: dict[str, int] = {}
            for note in metadata:
                folders[note["folder"]] = folders.get(note["folder"], 0) + 1

            lines = [
                "Writers Room Index",
                "=" * 30,
                f"Total notes indexed: {len(metadata)}",
                f"Embedding dimensions: {embeddings.shape[1] if len(embeddings) else 'N/A'}",
                "",
                "Notes by folder:",
            ]
            for folder, count in sorted(folders.items(), key=lambda x: -x[1]):
                lines.append(f"  {folder}: {count} notes")

            return [types.TextContent(type="text", text="\n".join(lines))]

        except RuntimeError as e:
            return [types.TextContent(type="text", text=str(e))]

    elif name == "reload_index":
        try:
            embeddings, metadata = reload_index()
            return [
                types.TextContent(
                    type="text",
                    text=f"Index reloaded. {len(metadata)} notes available.",
                )
            ]
        except RuntimeError as e:
            return [types.TextContent(type="text", text=str(e))]

    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
