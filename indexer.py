"""
Indexes notes from all configured sources into a local vector store.

Reads notes via source adapters (Apple Notes, Obsidian, Bear, etc.),
embeds with OpenAI, and saves as numpy arrays on disk for fast semantic search.

Usage:
    python3 indexer.py                          # incremental update (all sources)
    python3 indexer.py --force                  # re-embed everything
    python3 indexer.py --folders "Ideas,Poems"  # only index specific groups
    python3 indexer.py --sources "bear"         # only index specific sources
    python3 indexer.py --list-folders           # show all groups + note counts
    python3 indexer.py --list-sources           # show configured sources
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from source_config import get_active_adapters, list_sources

load_dotenv(Path(__file__).parent / ".env")

INDEX_DIR = Path(__file__).parent / "index"
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
METADATA_FILE = INDEX_DIR / "metadata.json"

EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 100

client = OpenAI()


def load_index() -> tuple[np.ndarray, list[dict]]:
    if EMBEDDINGS_FILE.exists() and METADATA_FILE.exists():
        embeddings = np.load(EMBEDDINGS_FILE)
        with open(METADATA_FILE, encoding='utf-8') as f:
            metadata = json.load(f)
        return embeddings, metadata
    return np.array([]).reshape(0, 0), []


def save_index(embeddings: np.ndarray, metadata: list[dict]) -> None:
    INDEX_DIR.mkdir(exist_ok=True)
    np.save(EMBEDDINGS_FILE, embeddings)
    with open(METADATA_FILE, "w", encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def embed_texts(texts: list[str]) -> list[list[float]]:
    all_embeddings = []
    total_batches = -(-len(texts) // BATCH_SIZE)  # ceiling division
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"    Embedding batch {batch_num}/{total_batches} ({len(batch)} notes)...")
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        all_embeddings.extend([e.embedding for e in response.data])
    return all_embeddings


MAX_CHARS = 24_000  # ~6k tokens, safely under the 8,192 token limit


def build_text_for_embedding(note: dict) -> str:
    """Combine title + source + folder + content for richer embedding."""
    source = note.get("source", "apple_notes")
    text = f"Title: {note['title']}\nSource: {source}\nFolder: {note['folder']}\n\n{note['content']}"
    return text[:MAX_CHARS] if len(text) > MAX_CHARS else text


def run_index(
    force: bool = False,
    folders: list[str] | None = None,
    sources: list[str] | None = None,
    on_progress=None,
) -> tuple[int, int]:
    """
    Build or update the search index, saving after each group.
    Resumable: if interrupted, re-running will skip already-indexed notes.

    Args:
        force: Re-embed even unchanged notes.
        folders: If set, only process these groups. Others are kept as-is.
        sources: If set, only process these source IDs. Others are kept as-is.
        on_progress: Optional callback(folder_index, total_folders, folder_name, notes_so_far, embedded_so_far)

    Returns:
        (total_indexed, num_updated)
    """
    start = time.time()

    # Load existing index
    existing_embeddings, existing_metadata = load_index()
    existing_by_id: dict[str, tuple[int, dict]] = {
        m["id"]: (i, m) for i, m in enumerate(existing_metadata)
    }

    # Get active adapters
    adapters = get_active_adapters()
    if sources:
        source_set = set(sources)
        adapters = [a for a in adapters if a.source_id in source_set]

    # Build the list of (adapter, group) pairs to process
    work: list[tuple] = []
    for adapter in adapters:
        groups = adapter.get_groups()
        if folders:
            groups = [g for g in groups if g in folders]
        for group in groups:
            work.append((adapter, group))

    total_work = len(work)
    if not total_work:
        print("Nothing to index.")
        return len(existing_metadata), 0

    adapter_names = {a.source_id: a.display_name for a in adapters}
    print(f"\nIndexing {total_work} groups from: {', '.join(adapter_names.values())}")

    total_updated = 0
    notes_so_far = 0

    for work_idx, (adapter, group_name) in enumerate(work, 1):
        source = adapter.source_id
        label = f"{adapter.display_name} / {group_name}"
        print(f"  [{work_idx}/{total_work}] {label}...", end=" ", flush=True)

        group_notes = adapter.read_group(group_name)

        if not group_notes:
            print("skipped")
            if on_progress:
                on_progress(work_idx, total_work, group_name, notes_so_far, total_updated)
            continue

        # Split into unchanged (reuse embedding) vs needs embedding
        to_reuse: list[tuple[dict, np.ndarray]] = []
        to_embed: list[dict] = []

        for note in group_notes:
            # Backward compat: inject source if missing
            if "source" not in note:
                note["source"] = source

            note_id = note["id"]
            if not force and note_id in existing_by_id:
                idx, existing = existing_by_id[note_id]
                if existing.get("modified") == note["modified"]:
                    # Reuse existing embedding, but update metadata (may have new fields)
                    to_reuse.append((note, existing_embeddings[idx]))
                    continue
            to_embed.append(note)

        print(f"{len(group_notes)} notes ({len(to_embed)} to embed)")

        new_embeddings: list[np.ndarray] = []
        if to_embed:
            texts = [build_text_for_embedding(n) for n in to_embed]
            new_embeddings = [np.array(e, dtype=np.float32) for e in embed_texts(texts)]
            total_updated += len(to_embed)

        notes_so_far += len(group_notes)

        # Merge: remove old entries for this (source, group), add fresh ones
        existing_embeddings, existing_metadata = load_index()
        kept_meta = [
            m for m in existing_metadata
            if not (m.get("source", "apple_notes") == source and m["folder"] == group_name)
        ]
        kept_emb = [
            existing_embeddings[i]
            for i, m in enumerate(existing_metadata)
            if not (m.get("source", "apple_notes") == source and m["folder"] == group_name)
        ]

        group_meta = [r[0] for r in to_reuse] + to_embed
        group_emb = [r[1] for r in to_reuse] + new_embeddings

        all_meta = kept_meta + group_meta
        all_emb = kept_emb + group_emb

        save_index(np.array(all_emb, dtype=np.float32), all_meta)

        # Refresh lookup for next iteration
        existing_embeddings, existing_metadata = load_index()
        existing_by_id = {m["id"]: (i, m) for i, m in enumerate(existing_metadata)}

        if on_progress:
            on_progress(work_idx, total_work, group_name, notes_so_far, total_updated)

    elapsed = time.time() - start
    _, final_metadata = load_index()
    print(f"\nDone. {len(final_metadata)} notes indexed, {total_updated} updated ({elapsed:.1f}s)")
    return len(final_metadata), total_updated


def list_folders() -> None:
    """Print all groups with their note counts, grouped by source."""
    _, metadata = load_index()

    # Group by source, then folder
    by_source: dict[str, dict[str, int]] = {}
    for m in metadata:
        source = m.get("source", "apple_notes")
        folder = m["folder"]
        by_source.setdefault(source, {})
        by_source[source][folder] = by_source[source].get(folder, 0) + 1

    for source, folders in sorted(by_source.items()):
        print(f"\n  {source}")
        print(f"  {'─' * 40}")
        for folder in sorted(folders):
            count = folders[folder]
            print(f"    {folder:<33} {count:>5}")
        print(f"    {'Total':<33} {sum(folders.values()):>5}")

    print(f"\n  Grand total: {len(metadata)} notes")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--list-sources" in args:
        list_sources()
        sys.exit(0)

    if "--list-folders" in args:
        list_folders()
        sys.exit(0)

    force = "--force" in args

    folders = None
    if "--folders" in args:
        idx = args.index("--folders")
        folders = [f.strip() for f in args[idx + 1].split(",")]
        print(f"Targeting groups: {folders}")

    source_filter = None
    if "--sources" in args:
        idx = args.index("--sources")
        source_filter = [s.strip() for s in args[idx + 1].split(",")]
        print(f"Targeting sources: {source_filter}")

    if force:
        print("Force mode: re-embedding all notes in scope.")

    total, updated = run_index(force=force, folders=folders, sources=source_filter)
    print(f"\nDone. {total} notes indexed, {updated} updated.")
