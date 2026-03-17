"""
Writers Room — Searcher

Direct index search for the menu bar app. Loads embeddings.npy + metadata.json
once at startup and holds them in memory. No MCP overhead.

Search logic copied verbatim from server.py.
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent / ".env")

INDEX_DIR       = Path(__file__).parent / "index"
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
METADATA_FILE   = INDEX_DIR / "metadata.json"
EMBEDDING_MODEL = "text-embedding-3-small"

LRU_MAX = 50  # cached query embeddings

# URL detection — matches http/https URLs in query text
_URL_RE = re.compile(r'https?://[^\s<>"\']+')

# URL distillation prompt — extracts search themes from a fetched page
_URL_DISTILL_SYSTEM = """\
You are helping a writer search their personal notes library.

They want to find existing work that could match this external page (a submission call, \
prompt, article, theme, etc.). Extract the core creative themes, subjects, emotions, \
and ideas that a writer's notes might touch on.

Return a JSON object (no markdown fencing):
{
  "search_query": "5-15 words: core themes, emotions, subjects to search for in the writer's notes",
  "brief_summary": "One sentence: what this page is about or looking for"
}

Focus search_query on themes a writer would explore in personal notes — \
NOT logistics (deadlines, word counts, submission guidelines, formatting rules).\
"""

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

        # URL distillation cache: url → {"search_query": ..., "brief_summary": ...}
        self._url_cache: dict[str, dict] = {}

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
               use_hyde: bool = False, search_depth: int = 50,
               skip_short_notes: bool = True,
               excluded_folders: list[str] | None = None,
               on_status: "Callable[[str], None] | None" = None) -> list[dict]:
        """
        Search the index. Returns a list of result dicts:
            { title, folder, content, snippet, score }

        use_hyde:          embed a hypothetical note instead of the raw query.
        search_depth:      0 = literal/keyword-heavy, 100 = deep semantic.
        skip_short_notes:  filter out trivially short notes.
        excluded_folders:  folder names to exclude from results.
        on_status:         optional callback for status updates (e.g. "Reading link…").

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

        # ── URL-aware search ─────────────────────────────────────────
        # If the query contains a URL, fetch the page, distill themes,
        # and use the synthesized query for search.
        brief_summary = None
        url_match = _URL_RE.search(query)
        if url_match:
            url = url_match.group(0)
            user_context = _URL_RE.sub("", query).strip()
            # Strip common connectors left after URL removal
            user_context = re.sub(
                r'^(any|do i have|related to|matching|for|this|that|:|\s)+',
                '', user_context, flags=re.I,
            ).strip()

            resolved = self._resolve_url(url, user_context, on_status)
            if resolved:
                query = resolved["search_query"]
                brief_summary = resolved["brief_summary"]
                if on_status:
                    on_status("searching…")

        # ── Folder-aware filtering ──────────────────────────────────
        # Detect "in my Products folder", "from Ideas", etc.
        # If matched, hard-filter to that folder and strip the reference
        # from the embedding query so semantics focus on the actual topic.
        folder_match = self._extract_folder_filter(query, metadata)
        embed_query = query
        if folder_match:
            embed_query = folder_match["clean_query"]

        # Choose embedding strategy
        def _vec():
            if use_hyde:
                return self._get_embedding_hyde(embed_query)
            return self._get_embedding(embed_query)

        if mode == "keyword":
            scores = np.array([self._keyword_score(embed_query, note) for note in metadata])

        elif mode == "hybrid":
            query_vec = _vec()
            sem_scores = self._cosine_similarity(query_vec, embeddings)
            s_min, s_max = sem_scores.min(), sem_scores.max()
            sem_norm = (sem_scores - s_min) / (s_max - s_min + 1e-10)
            kw_scores = np.array([self._keyword_score(embed_query, note) for note in metadata])

            # Smart weighting: query analysis determines a base keyword weight,
            # then search_depth shifts it — low depth → keyword-heavy, high → semantic.
            kw_w = self._query_keyword_weight(embed_query)
            # search_depth 0→+0.3 to kw_w (more keyword), 100→-0.3 (more semantic)
            depth_shift = 0.3 - (search_depth / 100.0) * 0.6
            kw_w = max(0.05, min(0.95, kw_w + depth_shift))
            scores = (1.0 - kw_w) * sem_norm + kw_w * kw_scores

        else:  # semantic (default)
            query_vec = _vec()
            scores = self._cosine_similarity(query_vec, embeddings)

        # ── Excluded folders ─────────────────────────────────────────
        excluded = {f.lower() for f in (excluded_folders or [])}
        if excluded:
            for i, note in enumerate(metadata):
                if note["folder"].lower() in excluded:
                    scores[i] = -1.0

        # ── Folder filter (query-detected) ──────────────────────────
        if folder_match:
            target = folder_match["folder"].lower()
            for i, note in enumerate(metadata):
                if note["folder"].lower() != target:
                    scores[i] = -1.0  # hard exclude

        # ── Content quality gate ────────────────────────────────────
        if skip_short_notes:
            for i, note in enumerate(metadata):
                clen = len(note["content"].strip())
                if clen < 10:
                    scores[i] *= 0.01   # near-zero: "1", phone numbers, empty
                elif clen < 30:
                    scores[i] *= 0.15   # heavy penalty: single-line stubs
                elif clen < 60:
                    scores[i] *= 0.5    # moderate penalty: very short notes

        # ── Date-aware filtering ────────────────────────────────────
        year_range = self._extract_year_filter(query)
        if year_range:
            for i, note in enumerate(metadata):
                year = self._note_year(note)
                if year is None or not (year_range[0] <= year <= year_range[1]):
                    scores[i] *= 0.05

        top_indices = np.argsort(scores)[::-1][:n]

        # ── Score floor ─────────────────────────────────────────────
        # Don't return results that are clearly irrelevant.
        min_score = 0.1 if mode == "keyword" else 0.01
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < min_score:
                continue
            note = metadata[idx]
            result = {
                "title":   note["title"],
                "folder":  note["folder"],
                "content": note["content"],
                "snippet": self._make_snippet(note["content"]),
                "score":   score,
            }
            if brief_summary:
                result["brief_summary"] = brief_summary
            results.append(result)

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

    # ------------------------------------------------------------------
    # URL resolution
    # ------------------------------------------------------------------

    def _resolve_url(self, url: str, user_context: str,
                     on_status: "Callable[[str], None] | None" = None) -> dict | None:
        """
        Fetch a URL, distill its themes via GPT-4o-mini, return
        {"search_query": "...", "brief_summary": "..."} or None on failure.
        Results are cached by URL.
        """
        # Check cache first
        if url in self._url_cache:
            return self._url_cache[url]

        if on_status:
            on_status("reading link…")

        page_text = self._fetch_page_text(url)
        if not page_text:
            return None  # fetch failed — fall back to raw query

        if on_status:
            on_status("analyzing brief…")

        # Truncate page text to ~3000 chars to keep tokens low
        page_text = page_text[:3000]

        user_msg = ""
        if user_context:
            user_msg = f'The writer said: "{user_context}"\n\n'
        user_msg += f"Here is the content from the linked page:\n---\n{page_text}\n---"

        try:
            resp = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _URL_DISTILL_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=150,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = re.sub(r'^```\w*\n?', '', raw)
                raw = re.sub(r'\n?```$', '', raw)
            result = json.loads(raw)

            # Validate expected keys
            if "search_query" in result and "brief_summary" in result:
                self._url_cache[url] = result
                return result
        except Exception:
            pass  # JSON parse or API error — fall back to raw query

        return None

    @staticmethod
    def _fetch_page_text(url: str) -> str | None:
        """Fetch a URL and extract readable text. Returns None on failure."""
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
                ),
            })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove nav, footer, script, style elements
            for tag in soup(["nav", "footer", "script", "style", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # Collapse multiple blank lines
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text if text else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Folder detection
    # ------------------------------------------------------------------

    # Patterns that reference a folder. Group 1 captures the folder name.
    # Order matters — more specific patterns first; the last pattern ("from X")
    # only fires if the candidate matches a real folder name (checked in the method).
    _FOLDER_PATTERNS = [
        re.compile(r'\b(?:in|from|inside)\s+(?:my\s+)?["\u201c]?(.+?)["\u201d]?\s+folder\b', re.I),
        re.compile(r'\b(?:in|from|inside)\s+(?:the\s+)?["\u201c]?(.+?)["\u201d]?\s+folder\b', re.I),
        re.compile(r'\bfolder\s+["\u201c]?(.+?)["\u201d]?\b', re.I),
        # Bare "from X" / "in X" — only triggers if X is a known folder
        re.compile(r'\b(?:in|from)\s+(?:my\s+)?["\u201c]?(.+?)["\u201d]?\s*$', re.I),
    ]

    def _extract_folder_filter(self, query: str, metadata: list[dict]) -> dict | None:
        """
        Detect a folder reference in the query and match it to a real folder.
        Returns {"folder": "PRODUCTS", "clean_query": "..."} or None.
        """
        all_folders = list({n["folder"] for n in metadata})
        folder_lower_map = {f.lower(): f for f in all_folders}

        for pat in self._FOLDER_PATTERNS:
            m = pat.search(query)
            if not m:
                continue
            candidate = m.group(1).strip()
            cl = candidate.lower()

            # Exact (case-insensitive) match
            if cl in folder_lower_map:
                clean = (query[:m.start()] + query[m.end():]).strip()
                # Strip leftover connectors
                clean = re.sub(r'^(what|which|are|is|the|best|my)\s+', '', clean, flags=re.I).strip() or clean
                return {"folder": folder_lower_map[cl], "clean_query": clean or candidate}

            # Substring match — "products" matches "PRODUCTS"
            for fl, real in folder_lower_map.items():
                if cl in fl or fl in cl:
                    clean = (query[:m.start()] + query[m.end():]).strip()
                    clean = re.sub(r'^(what|which|are|is|the|best|my)\s+', '', clean, flags=re.I).strip() or clean
                    return {"folder": real, "clean_query": clean or candidate}

        return None

    def _extract_year_filter(self, query: str) -> tuple[int, int] | None:
        """Detect year references in query. Returns (start, end) or None."""
        # "between 2023 and 2025"
        m = re.search(r'between\s+(20\d{2})\s+and\s+(20\d{2})', query, re.I)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        # "from 2023 to 2025"
        m = re.search(r'from\s+(20\d{2})\s+to\s+(20\d{2})', query, re.I)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        # Single year: "in 2024", "2024", "during 2024"
        m = re.search(r'\b(20\d{2})\b', query)
        if m:
            y = int(m.group(1))
            return (y, y)
        return None

    def _note_year(self, note: dict) -> int | None:
        """Extract year from note's created date string."""
        m = re.search(r'\b(20\d{2})\b', note.get('created', ''))
        return int(m.group(1)) if m else None

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
