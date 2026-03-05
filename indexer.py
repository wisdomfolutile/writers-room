"""
Indexes Apple Notes into a local vector store.

Reads notes via AppleScript (batch per folder), embeds with OpenAI,
and saves as numpy arrays on disk for fast semantic search.

Usage:
    python3 indexer.py                          # incremental update (all folders)
    python3 indexer.py --force                  # re-embed everything
    python3 indexer.py --folders "Ideas,Poems"  # only index specific folders
    python3 indexer.py --list-folders           # show all folders + note counts
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from notes_reader import read_notes, get_folder_names

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


MAX_CHARS = 24_000  # ~6k tokens, safely under the 8192 token limit


def build_text_for_embedding(note: dict) -> str:
    """Combine title + folder + content for richer embedding. Truncates if too long."""
    text = f"Title: {note['title']}\nFolder: {note['folder']}\n\n{note['content']}"
    return text[:MAX_CHARS] if len(text) > MAX_CHARS else text


def run_index(
    force: bool = False,
    folders: list[str] | None = None,
) -> tuple[int, int]:
    """
    Build or update the search index, saving after each folder.
    Resumable: if interrupted, re-running will skip already-indexed notes.

    Args:
        force: Re-embed even unchanged notes.
        folders: If set, only process these folders. Others are kept as-is.

    Returns:
        (total_indexed, num_updated)
    """
    start = time.time()

    # Load existing index (used for incremental updates)
    existing_embeddings, existing_metadata = load_index()
    existing_by_id: dict[str, tuple[int, dict]] = {
        m["id"]: (i, m) for i, m in enumerate(existing_metadata)
    }

    target_folders = folders if folders is not None else get_folder_names()

    if folders:
        print(f"\nReading notes from folders: {', '.join(folders)}")
    else:
        print("\nReading notes from Apple Notes (all folders)...")

    total_updated = 0

    for folder_idx, folder_name in enumerate(target_folders, 1):
        print(f"  [{folder_idx}/{len(target_folders)}] {folder_name}...", end=" ", flush=True)

        folder_notes = read_notes(folders=[folder_name])

        if not folder_notes:
            print("skipped")
            continue

        # Split into unchanged (reuse embedding) vs needs embedding
        to_reuse: list[tuple[dict, np.ndarray]] = []
        to_embed: list[dict] = []

        for note in folder_notes:
            note_id = note["id"]
            if not force and note_id in existing_by_id:
                idx, existing = existing_by_id[note_id]
                if existing.get("modified") == note["modified"]:
                    to_reuse.append((existing, existing_embeddings[idx]))
                    continue
            to_embed.append(note)

        print(f"{len(folder_notes)} notes ({len(to_embed)} to embed)")

        new_embeddings: list[np.ndarray] = []
        if to_embed:
            texts = [build_text_for_embedding(n) for n in to_embed]
            new_embeddings = [np.array(e, dtype=np.float32) for e in embed_texts(texts)]
            total_updated += len(to_embed)

        # Merge this folder's results into the existing index
        # Remove any old entries for this folder, then add fresh ones
        existing_embeddings, existing_metadata = load_index()
        kept_meta = [m for m in existing_metadata if m["folder"] != folder_name]
        kept_emb = [
            existing_embeddings[i]
            for i, m in enumerate(existing_metadata)
            if m["folder"] != folder_name
        ]

        folder_meta = [r[0] for r in to_reuse] + to_embed
        folder_emb = [r[1] for r in to_reuse] + new_embeddings

        all_meta = kept_meta + folder_meta
        all_emb = kept_emb + folder_emb

        save_index(np.array(all_emb, dtype=np.float32), all_meta)

        # Refresh lookup for next iteration
        existing_embeddings, existing_metadata = load_index()
        existing_by_id = {m["id"]: (i, m) for i, m in enumerate(existing_metadata)}

    elapsed = time.time() - start
    _, final_metadata = load_index()
    print(f"\nDone. {len(final_metadata)} notes indexed, {total_updated} updated ({elapsed:.1f}s)")
    return len(final_metadata), total_updated


def list_folders() -> None:
    """Print all folders with their note counts from the current index."""
    _, metadata = load_index()
    indexed: dict[str, int] = {}
    for m in metadata:
        indexed[m["folder"]] = indexed.get(m["folder"], 0) + 1

    all_folders = get_folder_names()
    print(f"\n{'Folder':<35} {'Indexed':>8}")
    print("-" * 45)
    for folder in sorted(all_folders):
        count = indexed.get(folder, 0)
        marker = "  ✓" if count > 0 else ""
        print(f"{folder:<35} {count:>8}{marker}")
    print(f"\nTotal indexed: {len(metadata)}")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--list-folders" in args:
        list_folders()
        sys.exit(0)

    force = "--force" in args

    folders = None
    if "--folders" in args:
        idx = args.index("--folders")
        folders = [f.strip() for f in args[idx + 1].split(",")]
        print(f"Targeting folders: {folders}")

    if force:
        print("Force mode: re-embedding all notes in scope.")

    total, updated = run_index(force=force, folders=folders)
    print(f"\nDone. {total} notes indexed, {updated} updated.")
