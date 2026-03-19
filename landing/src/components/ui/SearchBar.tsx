import { useState, useRef, useCallback, useEffect } from "react";

interface DemoResult {
  title: string;
  folder: string;
  excerpt: string;
  score: number;
  mode: "semantic" | "keyword" | "hybrid";
}

interface DemoQuery {
  query: string;
  synthesis: string;
  results: DemoResult[];
}

const DEMO_DATA: DemoQuery[] = [
  {
    query: "what have I written about leaving home",
    synthesis:
      'You\'ve returned to this theme many times — the pull between roots and reinvention. Your piece in [[On Leaving]] is the most direct, but echoes show up in [[Lagos to London]] and [[Things I Forgot to Pack]].',
    results: [
      {
        title: "On Leaving",
        folder: "Essays",
        excerpt:
          "There's a particular kind of guilt that comes with choosing to leave. Not exile — that has dignity. This is voluntary departure, which means every homesick night is technically your fault...",
        score: 0.94,
        mode: "semantic",
      },
      {
        title: "Lagos to London",
        folder: "Drafts",
        excerpt:
          "The Heathrow arrivals hall smelled like carpet cleaner and cold air. I remember thinking: this is what starting over smells like. Sterile. No pepper soup in the atmosphere...",
        score: 0.89,
        mode: "semantic",
      },
      {
        title: "Things I Forgot to Pack",
        folder: "Poems",
        excerpt:
          "My mother's voice at 6am, calling\nfrom the kitchen where garri soaks\nin water overnight—I forgot to pack\nthe sound of morning...",
        score: 0.86,
        mode: "semantic",
      },
    ],
  },
  {
    query: "poems about faith",
    synthesis:
      "You've wrestled with faith across multiple pieces — sometimes directly, sometimes through metaphor. [[Vespers]] is your most structured liturgical poem, while [[God of Small Margins]] approaches doubt through the lens of everyday uncertainty.",
    results: [
      {
        title: "Vespers",
        folder: "Poems",
        excerpt:
          "I still pray, though I'm not sure to whom.\nHabit or hope — does it matter which?\nThe words rise like smoke from a candle\nlit for someone who may not be listening...",
        score: 0.92,
        mode: "semantic",
      },
      {
        title: "God of Small Margins",
        folder: "Poems",
        excerpt:
          "He lives in the space between\nalmost and enough, in the breath\nbefore the answer comes back negative.\nThis god is not omnipotent — just persistent...",
        score: 0.88,
        mode: "semantic",
      },
      {
        title: "Sunday Mornings After",
        folder: "Drafts",
        excerpt:
          "We stopped going to church the summer Dad got sick. Not dramatically — no grand rejection. We just... stopped. The alarm still went off at 6:30, and nobody moved...",
        score: 0.84,
        mode: "semantic",
      },
    ],
  },
  {
    query: "startup ideas",
    synthesis:
      "You've accumulated quite a few ideas over the years — ranging from practical tools to ambitious platforms. [[Marketplace for African Creatives]] has the most detailed notes, while [[Writers Room]] is the one you actually built.",
    results: [
      {
        title: "Marketplace for African Creatives",
        folder: "Ideas",
        excerpt:
          "Platform connecting diaspora buyers with local artists. Commission-based model. Key insight: the trust gap isn't about payment processing — it's about curation...",
        score: 0.91,
        mode: "semantic",
      },
      {
        title: "Writers Room",
        folder: "Products",
        excerpt:
          "What if you could search your notes by meaning, not just keywords? Semantic search over Apple Notes. Use embeddings to find connections you didn't know existed...",
        score: 0.87,
        mode: "semantic",
      },
      {
        title: "Focus Timer with Stakes",
        folder: "Ideas",
        excerpt:
          "Pomodoro app where you put money on the line. Miss your focus session, donation goes to a cause you dislike. Accountability through mild financial threat...",
        score: 0.82,
        mode: "semantic",
      },
    ],
  },
  {
    query: "that recipe from Aunty Bisi",
    synthesis:
      "Found it — [[Aunty Bisi's Jollof]] has the full recipe with her specific instructions about the tomato base and the bay leaf timing.",
    results: [
      {
        title: "Aunty Bisi's Jollof",
        folder: "Recipes",
        excerpt:
          'The secret, she said, is patience with the tomato base. "Let it fry until the oil floats on top. If you rush this part, the rice will taste like stew, not jollof." Two bay leaves, not three...',
        score: 0.95,
        mode: "hybrid",
      },
      {
        title: "Christmas 2023 Menu",
        folder: "Personal",
        excerpt:
          "Aunty Bisi is bringing the jollof (thank God). I'm on drinks and small chops. Need to sort: puff puff, spring rolls, peppered chicken. Remind Chidi about the cooler...",
        score: 0.78,
        mode: "hybrid",
      },
    ],
  },
  {
    query: "reflections on identity",
    synthesis:
      'This is one of your deepest threads — identity shows up everywhere from your poetry to your journal entries. [[Hyphenated]] is probably your most focused meditation on it, exploring what it means to be Nigerian-British.',
    results: [
      {
        title: "Hyphenated",
        folder: "Essays",
        excerpt:
          "The hyphen in Nigerian-British does a lot of heavy lifting. It's asked to bridge two continents, two value systems, two ways of laughing at different things. Sometimes the hyphen feels more like a fault line...",
        score: 0.93,
        mode: "semantic",
      },
      {
        title: "Code Switching",
        folder: "Poems",
        excerpt:
          "In the office I am articulate,\nwhich is a word that means\nyou expected less.\nAt home I am just Wisdom,\nand my English has hips...",
        score: 0.89,
        mode: "semantic",
      },
      {
        title: "Third Culture Notes",
        folder: "Journal",
        excerpt:
          "Had that conversation again today — 'where are you really from?' I've started answering with coordinates. Latitude 6.5244, Longitude 3.3792. It's more honest than any single word...",
        score: 0.85,
        mode: "semantic",
      },
    ],
  },
];

function fuzzyMatch(input: string, queries: DemoQuery[]): DemoQuery | null {
  const normalised = input.toLowerCase().trim();
  if (normalised.length < 3) return null;

  let bestMatch: DemoQuery | null = null;
  let bestScore = 0;

  for (const dq of queries) {
    const target = dq.query.toLowerCase();
    const inputWords = normalised.split(/\s+/);
    const matchedWords = inputWords.filter((w) => target.includes(w));
    const score = matchedWords.length / inputWords.length;

    if (score > bestScore && score >= 0.4) {
      bestScore = score;
      bestMatch = dq;
    }
  }

  return bestMatch;
}

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DemoResult[]>([]);
  const [synthesis, setSynthesis] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [activeMode, setActiveMode] = useState<"semantic" | "hybrid" | "keyword">("semantic");
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(
    (q: string) => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);

      if (q.trim().length < 3) {
        setResults([]);
        setSynthesis("");
        setHasSearched(false);
        setIsSearching(false);
        return;
      }

      setIsSearching(true);
      timeoutRef.current = setTimeout(() => {
        const match = fuzzyMatch(q, DEMO_DATA);
        if (match) {
          setSynthesis(match.synthesis);
          setResults(match.results);
        } else {
          setSynthesis("");
          setResults([]);
        }
        setHasSearched(true);
        setIsSearching(false);
      }, 400);
    },
    [],
  );

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    search(val);
  };

  // Render [[Note Title]] as teal text
  const renderSynthesis = (text: string) => {
    const parts = text.split(/(\[\[.*?\]\])/g);
    return parts.map((part, i) => {
      if (part.startsWith("[[") && part.endsWith("]]")) {
        return (
          <span key={i} className="text-teal font-medium">
            {part}
          </span>
        );
      }
      return part;
    });
  };

  const suggestedQueries = [
    "what have I written about leaving home",
    "poems about faith",
    "startup ideas",
    "that recipe from Aunty Bisi",
    "reflections on identity",
  ];

  return (
    <div className="max-w-2xl mx-auto">
      {/* Search bar */}
      <div className="glass rounded-2xl p-1.5 shadow-lg shadow-black/5">
        <div className="flex items-center gap-3 bg-apple-card-solid/60 rounded-xl px-5 py-4">
          <svg
            className="w-5 h-5 text-apple-text-secondary shrink-0"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            type="text"
            value={query}
            onChange={handleInput}
            placeholder="What are you looking for?"
            className="flex-1 bg-transparent text-[17px] text-apple-text placeholder:text-apple-text-secondary outline-none"
          />
          {/* Mode pills */}
          <div className="hidden sm:flex items-center gap-1">
            {(["semantic", "hybrid", "keyword"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setActiveMode(mode)}
                className={`px-2 py-0.5 text-[11px] font-semibold rounded-md transition-colors ${
                  activeMode === mode
                    ? "bg-gold text-apple-code-bg"
                    : "text-apple-text-secondary hover:bg-apple-bg-alt"
                }`}
              >
                {mode[0].toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Suggested queries */}
      {!hasSearched && !query && (
        <div className="mt-4 flex flex-wrap gap-2 justify-center">
          {suggestedQueries.map((sq) => (
            <button
              key={sq}
              onClick={() => {
                setQuery(sq);
                search(sq);
              }}
              className="px-3 py-1.5 text-[13px] text-apple-text-secondary bg-apple-card-solid/70 border border-apple-border/40 rounded-full hover:border-gold/40 hover:text-gold-text transition-colors"
            >
              {sq}
            </button>
          ))}
        </div>
      )}

      {/* Loading state */}
      {isSearching && (
        <div className="mt-6 text-center text-sm text-apple-text-secondary">
          <span className="inline-block animate-pulse">Searching...</span>
        </div>
      )}

      {/* Synthesis */}
      {synthesis && !isSearching && (
        <div className="mt-6 p-4 rounded-xl bg-apple-card-solid/50 border border-apple-border/30">
          <p className="text-[15px] text-apple-text leading-relaxed">
            {renderSynthesis(synthesis)}
          </p>
        </div>
      )}

      {/* Results */}
      {results.length > 0 && !isSearching && (
        <div className="mt-4 space-y-3">
          {results.map((r, i) => (
            <div
              key={i}
              className="group p-5 rounded-xl bg-apple-card-solid/70 border border-apple-border/30 hover:border-gold/20 hover:shadow-md transition-all duration-200"
              style={{
                animation: `fadeSlideUp 0.4s ease-out ${i * 0.1}s both`,
              }}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2.5">
                  <h4 className="text-[15px] font-semibold text-apple-text">
                    {r.title}
                  </h4>
                  <span className="px-2 py-0.5 text-[11px] font-medium text-apple-text-secondary bg-apple-bg-alt rounded-md">
                    {r.folder}
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[12px] font-mono text-apple-text-secondary">
                    {r.score.toFixed(2)}
                  </span>
                  <button className="w-7 h-7 rounded-lg flex items-center justify-center text-apple-text-secondary hover:bg-apple-bg-alt transition-colors">
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M7 17L17 7M17 7H7M17 7v10" />
                    </svg>
                  </button>
                </div>
              </div>
              <p className="text-[14px] text-apple-text-secondary leading-relaxed line-clamp-2">
                {r.excerpt}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* No results */}
      {hasSearched && !isSearching && results.length === 0 && query.length >= 3 && (
        <div className="mt-6 text-center text-sm text-apple-text-secondary">
          Try one of the suggested queries above to see the demo in action.
        </div>
      )}

      <style>{`
        @keyframes fadeSlideUp {
          from {
            opacity: 0;
            transform: translateY(12px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>
    </div>
  );
}
