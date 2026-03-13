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

# HyDE system prompt — tells the model to write a plausible note excerpt
_HYDE_SYSTEM = (
    "You are helping search a writer's personal notes. "
    "Given the writer's query, write a short note excerpt (2–3 sentences, first person) "
    "that would directly answer it. Be specific about themes, emotions, and topics. "
    "No title, no metadata — just the note content itself."
)


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

    def search(self, query: str, n: int = 5, mode: str = "semantic",
               use_hyde: bool = False) -> list[dict]:
        """
        Search the index. Returns a list of result dicts:
            { title, folder, content, snippet, score }

        use_hyde: embed a GPT-generated hypothetical note instead of the raw query.
                  Dramatically improves recall for conversational / reflective queries.

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

        # Choose embedding strategy
        def _vec():
            if use_hyde:
                return self._get_embedding_hyde(query)
            return self._get_embedding(query)

        if mode == "keyword":
            scores = np.array([self._keyword_score(query, note) for note in metadata])

        elif mode == "hybrid":
            query_vec = _vec()
            sem_scores = self._cosine_similarity(query_vec, embeddings)
            s_min, s_max = sem_scores.min(), sem_scores.max()
            sem_norm = (sem_scores - s_min) / (s_max - s_min + 1e-10)
            kw_scores = np.array([self._keyword_score(query, note) for note in metadata])

            # Smart weighting: specific lookups lean keyword, exploratory leans semantic
            kw_w = self._query_keyword_weight(query)
            scores = (1.0 - kw_w) * sem_norm + kw_w * kw_scores

        else:  # semantic (default)
            query_vec = _vec()
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
        content_lower = note["content"].lower()
        title_lower = note["title"].lower()
        text = title_lower + " " + content_lower
        q = query.lower()

        # Exact phrase match in full text
        if q in text:
            return 1.0

        words = [w for w in q.split() if len(w) > 1]  # drop single chars
        if not words:
            return 0.0

        hits = sum(1 for w in words if w in text)
        base = hits / len(words)

        # Conjunction bonus: ALL words present → strong signal of relevance
        if hits == len(words) and len(words) >= 2:
            base = min(1.0, base + 0.3)

        # Title match bonus: words in title are high-signal
        title_hits = sum(1 for w in words if w in title_lower)
        if title_hits > 0:
            base = min(1.0, base + 0.15 * title_hits / len(words))

        return base

    def _query_keyword_weight(self, query: str) -> float:
        """Analyze query to determine keyword vs semantic balance.

        Returns keyword weight (0.0–1.0). Semantic weight = 1 - this.

        Specific lookups (names, possessives, numbers) lean keyword-heavy.
        Exploratory/thematic queries lean semantic-heavy.
        """
        words = query.split()
        signals = 0

        # Possessive → looking for a specific person's thing
        if "\u2019s " in query or "'s " in query:
            signals += 2

        # Proper nouns (capitalized words after the first)
        for w in words[1:]:
            if len(w) > 1 and w[0].isupper():
                signals += 1

        # First word capitalized + not a common sentence starter
        if words and words[0][0].isupper() and words[0].lower() not in {
            "what", "where", "when", "how", "why", "which", "who",
            "find", "show", "get", "list", "search", "tell", "give",
            "have", "do", "did", "is", "are", "was", "were", "the",
            "that", "this", "my", "a", "an", "any", "all", "every",
        }:
            signals += 1

        # Contains digits (dates, phone numbers, addresses)
        if any(c.isdigit() for c in query):
            signals += 2

        # Short specific query (1-3 words) → likely a lookup
        if len(words) <= 3:
            signals += 1

        # Quoted phrases
        if '"' in query or '\u201c' in query:
            signals += 2

        # Map: 0 signals → 0.3 keyword (semantic-heavy),
        #       5+ signals → 0.8 keyword (keyword-heavy)
        return min(0.8, 0.3 + signals * 0.1)

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

    def _get_embedding_hyde(self, query: str) -> np.ndarray:
        """
        HyDE: ask GPT-4o-mini to write a hypothetical note that answers this query,
        then embed that instead of the raw question.

        Because the hypothetical is a first-person statement like real note content,
        it lands much closer in embedding space to actual relevant notes — especially
        for reflective / conversational queries like "what have I been writing about grief?"
        """
        cache_key = f"__hyde__{query}"
        if cache_key in self._cache:
            self._cache_order.remove(cache_key)
            self._cache_order.append(cache_key)
            return self._cache[cache_key]

        # Step 1: generate hypothetical note
        chat = self._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _HYDE_SYSTEM},
                {"role": "user",   "content": query},
            ],
            max_tokens=120,
            temperature=0.7,
        )
        hypothetical = chat.choices[0].message.content.strip()

        # Step 2: embed it
        embed_resp = self._client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[hypothetical],
        )
        vec = np.array(embed_resp.data[0].embedding, dtype=np.float32)

        self._cache[cache_key] = vec
        self._cache_order.append(cache_key)
        if len(self._cache_order) > LRU_MAX:
            oldest = self._cache_order.pop(0)
            del self._cache[oldest]

        return vec

    def _make_snippet(self, content: str, n_chars: int = 160) -> str:
        """First ≤n_chars of content, truncated to a word boundary."""
        content = content.strip()
        if len(content) <= n_chars:
            return content
        truncated = content[:n_chars]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        return truncated + "…"
