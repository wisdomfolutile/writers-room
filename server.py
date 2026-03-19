"""
Writers Room MCP Server

Exposes your Apple Notes index to Claude as searchable tools.

Tools:
    search_notes(query, n_results, mode)  — semantic, keyword, or hybrid search
    index_status()                        — show how many notes are indexed
"""

import asyncio
import json
import re
from pathlib import Path

import numpy as np
import requests
from bs4 import BeautifulSoup
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
        with open(METADATA_FILE, encoding='utf-8') as f:
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


# ── URL resolution for MCP ────────────────────────────────────────────

_URL_DISTILL_SYSTEM = (
    "You are helping a writer search their personal notes library.\n\n"
    "They want to find existing work that could match this external page (a submission call, "
    "prompt, article, theme, etc.). Extract the core creative themes, subjects, emotions, "
    "and ideas that a writer's notes might touch on.\n\n"
    "Return a JSON object (no markdown fencing):\n"
    '{\n  "search_query": "5-15 words: core themes, emotions, subjects to search for",\n'
    '  "brief_summary": "One sentence: what this page is about or looking for"\n}\n\n'
    "Focus search_query on themes a writer would explore in personal notes — "
    "NOT logistics (deadlines, word counts, submission guidelines)."
)

_url_cache: dict[str, dict] = {}


def _resolve_url_for_mcp(url: str, user_context: str) -> dict | None:
    """Fetch a URL and distill search themes. Cached by URL."""
    if url in _url_cache:
        return _url_cache[url]
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
            ),
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["nav", "footer", "script", "style", "header", "aside"]):
            tag.decompose()
        page_text = soup.get_text(separator="\n", strip=True)[:3000]
        if not page_text:
            return None
    except Exception:
        return None

    user_msg = ""
    if user_context:
        user_msg = f'The writer said: "{user_context}"\n\n'
    user_msg += f"Here is the content from the linked page:\n---\n{page_text}\n---"

    try:
        chat = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _URL_DISTILL_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=150,
            temperature=0.3,
        )
        raw = chat.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = re.sub(r'^```\w*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
        result = json.loads(raw)
        if "search_query" in result and "brief_summary" in result:
            _url_cache[url] = result
            return result
    except Exception:
        pass
    return None


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_notes",
            description=(
                "Search through the user's notes (Apple Notes, Obsidian, Bear, and more). "
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
                "Check how many notes are indexed in Writers Room, "
                "and see the breakdown by source and folder."
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

        # ── URL-aware search ─────────────────────────────────────
        brief_summary = None
        url_match = re.search(r'https?://[^\s<>"\']+', query)
        if url_match:
            url = url_match.group(0)
            user_context = re.sub(r'https?://[^\s<>"\']+', '', query).strip()
            user_context = re.sub(
                r'^(any|do i have|related to|matching|for|this|that|:|\s)+',
                '', user_context, flags=re.I,
            ).strip()
            resolved = _resolve_url_for_mcp(url, user_context)
            if resolved:
                query = resolved["search_query"]
                brief_summary = resolved["brief_summary"]

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

        output_lines = []
        if brief_summary:
            output_lines.append(f"🔗 URL Brief: {brief_summary}")
            output_lines.append(f"   Searching for: {query}\n")
        output_lines.append(f"Found {n} notes for: '{query}'\n")
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
            source = note.get("source", "apple_notes")
            source_label = source.replace("_", " ").title()
            output_lines += [
                f"{'=' * 60}",
                f"[{rank}] {note['title']}",
                f"Source: {source_label}  |  Folder: {note['folder']}  |  Modified: {note['modified']}  |  Relevance: {score:.3f}",
                f"🔍 Find in Notes: search {search_hint} (folder: {note['folder']})",
                "",
                note["content"],
                "",
            ]

        return [types.TextContent(type="text", text="\n".join(output_lines))]

    elif name == "index_status":
        try:
            embeddings, metadata = load_index()

            # Group by source, then folder
            by_source: dict[str, dict[str, int]] = {}
            for note in metadata:
                source = note.get("source", "apple_notes")
                folder = note["folder"]
                by_source.setdefault(source, {})
                by_source[source][folder] = by_source[source].get(folder, 0) + 1

            lines = [
                "Writers Room Index",
                "=" * 30,
                f"Total notes indexed: {len(metadata)}",
                f"Sources: {len(by_source)}",
                f"Embedding dimensions: {embeddings.shape[1] if len(embeddings) else 'N/A'}",
            ]
            for source, folders in sorted(by_source.items()):
                source_total = sum(folders.values())
                source_label = source.replace("_", " ").title()
                lines.append(f"\n{source_label} ({source_total} notes):")
                for folder, count in sorted(folders.items(), key=lambda x: -x[1]):
                    lines.append(f"  {folder}: {count}")

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
