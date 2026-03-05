"""
Writers Room — Searcher

Direct index search for the menu bar app. Loads embeddings.npy + metadata.json
once at startup and holds them in memory. No MCP overhead.

Search logic copied verbatim from server.py.
"""

import json
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent / ".env")

INDEX_DIR       = Path(__file__).parent / "index"
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
METADATA_FILE   = INDEX_DIR / "metadata.json"
EMBEDDING_MODEL = "text-embedding-3-small"

LRU_MAX = 50  # cached query embeddings


class NotesSearcher:
    """
    Owns the in-memory index. Thread-safe for reads after load_index().
    All OpenAI API calls happen on whichever thread calls search() —
    the caller is responsible for running search() off the main thread.
    """

    def __init__(self) -> None:
        self._embeddings: np.ndarray | None = None
        self._metadata: list[dict] | None = None
        self._client: OpenAI | None = None

        # LRU embedding cache: dict for fast lookup, list for order
        self._cache: dict[str, np.ndarray] = {}
        self._cache_order: list[str] = []

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def load_index(self) -> None:
        """Load from disk. Safe to call from a background thread."""
        if not EMBEDDINGS_FILE.exists():
            raise RuntimeError(
                f"Index not found at {EMBEDDINGS_FILE}. Run: python3 indexer.py"
            )
        self._embeddings = np.load(EMBEDDINGS_FILE)
        with open(METADATA_FILE, encoding='utf-8') as f:
            self._metadata = json.load(f)
        self._client = OpenAI()

    def reload_index(self) -> int:
        """Re-load from disk after re-indexing. Returns new note count."""
        self._embeddings = np.load(EMBEDDINGS_FILE)
        with open(METADATA_FILE, encoding='utf-8') as f:
            self._metadata = json.load(f)
        # Clear embedding cache — stale after re-index (content may have changed)
        self._cache.clear()
        self._cache_order.clear()
        return len(self._metadata)

    @property
    def is_loaded(self) -> bool:
        return self._embeddings is not None and self._metadata is not None

    @property
    def note_count(self) -> int:
        return len(self._metadata) if self._metadata else 0

    # ------------------------------------------------------------------
    # Public search
    # ------------------------------------------------------------------

    def search(self, query: str, n: int = 5, mode: str = "semantic") -> list[dict]:
        """
        Search the index. Returns a list of result dicts:
            { title, folder, content, snippet, score }

        Safe to call from a background thread.
        Raises RuntimeError if index has not been loaded.
        """
        if not self.is_loaded:
            raise RuntimeError("Index not loaded. Call load_index() first.")

        query = query.strip()
        if not query:
            return []

        embeddings = self._embeddings
        metadata   = self._metadata

        if mode == "keyword":
            scores = np.array([self._keyword_score(query, note) for note in metadata])

        elif mode == "hybrid":
            query_vec = self._get_embedding(query)
            sem_scores = self._cosine_similarity(query_vec, embeddings)
            s_min, s_max = sem_scores.min(), sem_scores.max()
            sem_norm = (sem_scores - s_min) / (s_max - s_min + 1e-10)
            kw_scores = np.array([self._keyword_score(query, note) for note in metadata])
            scores = 0.5 * sem_norm + 0.5 * kw_scores

        else:  # semantic (default)
            query_vec = self._get_embedding(query)
            scores = self._cosine_similarity(query_vec, embeddings)

        top_indices = np.argsort(scores)[::-1][:n]

        results = []
        for idx in top_indices:
            note  = metadata[idx]
            score = float(scores[idx])
            results.append({
                "title":   note["title"],
                "folder":  note["folder"],
                "content": note["content"],
                "snippet": self._make_snippet(note["content"]),
                "score":   score,
            })

        return results

    # ------------------------------------------------------------------
    # Private helpers — search logic (verbatim from server.py)
    # ------------------------------------------------------------------

    def _cosine_similarity(self, query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
        norms  = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
        normed = matrix / norms
        return normed @ query_norm

    def _keyword_score(self, query: str, note: dict) -> float:
        text = (note["title"] + " " + note["content"]).lower()
        q    = query.lower()

        if q in text:
            return 1.0

        words = q.split()
        hits  = sum(1 for w in words if w in text)
        return hits / len(words) if words else 0.0

    def _get_embedding(self, query: str) -> np.ndarray:
        """Returns query embedding, using LRU cache to avoid redundant API calls."""
        if query in self._cache:
            # Move to most-recently-used position
            self._cache_order.remove(query)
            self._cache_order.append(query)
            return self._cache[query]

        response = self._client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[query],
        )
        vec = np.array(response.data[0].embedding, dtype=np.float32)

        self._cache[query] = vec
        self._cache_order.append(query)

        # Evict oldest if over limit
        if len(self._cache_order) > LRU_MAX:
            oldest = self._cache_order.pop(0)
            del self._cache[oldest]

        return vec

    def _make_snippet(self, content: str, n_chars: int = 80) -> str:
        """First ≤n_chars of content, truncated to a word boundary."""
        content = content.strip()
        if len(content) <= n_chars:
            return content
        truncated = content[:n_chars]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        return truncated + "…"
