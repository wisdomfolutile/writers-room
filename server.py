"""
Writers Room MCP Server

Exposes your notes index to Claude as searchable tools.

All search logic lives in searcher.NotesSearcher — the same engine the
menu bar app's Python tooling uses. The server is a thin MCP adapter:
it owns tool schemas and output formatting, nothing else. (It previously
carried a drifted duplicate of the scoring code; consolidating onto
NotesSearcher gave MCP users temporal queries, folder detection, the
LRU embedding cache, and smart hybrid weighting for free.)

Tools:
    search_notes(query, n_results, mode)  — semantic, keyword, or hybrid search
    index_status()                        — show how many notes are indexed
    reload_index()                        — reload after re-indexing
"""

import asyncio
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from searcher import NotesSearcher

server = Server("writers-room")
searcher = NotesSearcher()


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
                "Understands temporal references (\"December 2023\", \"last summer\") and "
                "folder references (\"in my Ideas folder\") inside the query. "
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
                            "'hybrid' — blends both with query-adaptive weighting."
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


def _format_results(query: str, results: list[dict]) -> str:
    output_lines = []

    brief_summary = results[0].get("brief_summary") if results else None
    if brief_summary:
        output_lines.append(f"🔗 URL Brief: {brief_summary}\n")

    output_lines.append(f"Found {len(results)} notes for: '{query}'\n")
    for rank, note in enumerate(results, 1):
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
        source_label = note.get("source", "apple_notes").replace("_", " ").title()
        output_lines += [
            f"{'=' * 60}",
            f"[{rank}] {note['title']}",
            f"Source: {source_label}  |  Folder: {note['folder']}  |  "
            f"Modified: {note.get('modified', '')}  |  Relevance: {note['score']:.3f}",
            f"🔍 Find in Notes: search {search_hint} (folder: {note['folder']})",
            "",
            note["content"],
            "",
        ]
    return "\n".join(output_lines)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "search_notes":
        query = arguments["query"]
        n = min(int(arguments.get("n_results", 5)), 20)
        mode = arguments.get("mode", "semantic")

        if not searcher.is_loaded:
            await asyncio.to_thread(searcher.load_index)

        # to_thread: the embedding API call and scoring are blocking
        results = await asyncio.to_thread(searcher.search, query, n, mode)
        return [types.TextContent(type="text", text=_format_results(query, results))]

    elif name == "index_status":
        try:
            if not searcher.is_loaded:
                await asyncio.to_thread(searcher.load_index)

            # Group by source, then folder
            by_source: dict[str, dict[str, int]] = {}
            for note in searcher.metadata:
                source = note.get("source", "apple_notes")
                folder = note["folder"]
                by_source.setdefault(source, {})
                by_source[source][folder] = by_source[source].get(folder, 0) + 1

            lines = [
                "Writers Room Index",
                "=" * 30,
                f"Total notes indexed: {searcher.note_count}",
                f"Sources: {len(by_source)}",
                f"Embedding dimensions: {searcher.embedding_dims or 'N/A'}",
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
            count = await asyncio.to_thread(
                searcher.reload_index if searcher.is_loaded else searcher.load_index
            )
            count = searcher.note_count
            return [
                types.TextContent(
                    type="text",
                    text=f"Index reloaded. {count} notes available.",
                )
            ]
        except RuntimeError as e:
            return [types.TextContent(type="text", text=str(e))]

    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    # Preload the index before serving so the first search doesn't pay
    # the load cost. A missing index is not fatal — tools report it.
    try:
        await asyncio.to_thread(searcher.load_index)
        print(f"writers-room: index preloaded ({searcher.note_count} notes)", file=sys.stderr)
    except Exception as e:
        print(f"writers-room: index not preloaded: {e}", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
