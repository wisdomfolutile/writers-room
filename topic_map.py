"""
Writers Room — Mind Constellation

Generates a 2D topic map from note embeddings using UMAP + K-means.
Clusters are auto-labeled via GPT-4o-mini. Output is saved as
index/topic_map.json for the Swift app to visualize.

Usage:
    python3 topic_map.py              # generate/update topic map
    python3 topic_map.py --force      # regenerate from scratch
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent / ".env")

INDEX_DIR = Path(__file__).parent / "index"
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
METADATA_FILE = INDEX_DIR / "metadata.json"
TOPIC_MAP_FILE = INDEX_DIR / "topic_map.json"

# Curated color palette — 25 distinct, vibrant colors that pop on dark backgrounds
_PALETTE = [
    "#FF6B6B",  # coral
    "#4ECDC4",  # teal
    "#FFE66D",  # gold
    "#A8E6CF",  # mint
    "#FF8A5C",  # tangerine
    "#6C5CE7",  # indigo
    "#FD79A8",  # rose
    "#00B894",  # emerald
    "#FDCB6E",  # amber
    "#74B9FF",  # cerulean
    "#E17055",  # copper
    "#81ECEC",  # aqua
    "#FAB1A0",  # peach
    "#A29BFE",  # lavender
    "#55EFC4",  # lime
    "#DFE6E9",  # silver
    "#F8A5C2",  # pink
    "#778BEB",  # periwinkle
    "#F3A683",  # sand
    "#63CDDA",  # sky
    "#CF6A87",  # mauve
    "#786FA6",  # purple
    "#F19066",  # salmon
    "#3DC1D3",  # cyan
    "#E77F67",  # sienna
]


def load_index() -> tuple[np.ndarray, list[dict]]:
    """Load embeddings and metadata from disk."""
    embeddings = np.load(EMBEDDINGS_FILE)
    with open(METADATA_FILE, encoding="utf-8") as f:
        metadata = json.load(f)
    return embeddings, metadata


def find_optimal_k(embeddings: np.ndarray, k_range: range = range(12, 28)) -> int:
    """Find optimal cluster count using silhouette score."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    print(f"  Finding optimal k in range {k_range.start}–{k_range.stop - 1}...")

    best_k, best_score = k_range.start, -1

    for k in k_range:
        km = KMeans(n_clusters=k, n_init=10, random_state=42, max_iter=300)
        labels = km.fit_predict(embeddings)
        score = silhouette_score(embeddings, labels, sample_size=min(3000, len(embeddings)))
        print(f"    k={k:2d}  silhouette={score:.4f}")
        if score > best_score:
            best_score = score
            best_k = k

    print(f"  Best: k={best_k} (silhouette={best_score:.4f})")
    return best_k


def cluster_embeddings(embeddings: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Run K-means clustering. Returns (labels, centroids)."""
    from sklearn.cluster import KMeans

    print(f"  Clustering into {k} groups...")
    km = KMeans(n_clusters=k, n_init=10, random_state=42, max_iter=300)
    labels = km.fit_predict(embeddings)
    return labels, km.cluster_centers_


def reduce_to_2d(embeddings: np.ndarray) -> np.ndarray:
    """Project embeddings to 2D via UMAP."""
    import umap

    print(f"  UMAP: {embeddings.shape[0]} points, {embeddings.shape[1]}D → 2D...")
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=30,
        min_dist=0.3,
        metric="cosine",
        random_state=42,
        verbose=False,
    )
    coords_2d = reducer.fit_transform(embeddings)

    # Normalize to [0, 1] range
    mins = coords_2d.min(axis=0)
    maxs = coords_2d.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1  # avoid division by zero
    coords_2d = (coords_2d - mins) / ranges

    return coords_2d


def label_clusters(
    metadata: list[dict],
    labels: np.ndarray,
    k: int,
) -> list[str]:
    """Generate human-readable labels for each cluster using GPT-4o-mini."""
    client = OpenAI()
    cluster_labels = []

    print(f"  Labeling {k} clusters via GPT-4o-mini...")

    for cluster_id in range(k):
        # Get notes in this cluster, sorted by content length (richest first)
        cluster_notes = [
            (i, metadata[i])
            for i in range(len(metadata))
            if labels[i] == cluster_id
        ]
        cluster_notes.sort(key=lambda x: len(x[1].get("content", "")), reverse=True)

        # Take top 10 representative notes
        sample = cluster_notes[:10]
        sample_text = "\n".join(
            f"- [{m['folder']}] {m['title']}: {m.get('content', '')[:200]}"
            for _, m in sample
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are labeling a cluster of a writer's personal notes. "
                            "Given sample notes from the cluster, generate a short, evocative label "
                            "(2-4 words) that captures the theme. Be specific and poetic, not generic. "
                            "Examples: 'Nigerian Identity', 'Love & Longing', 'Startup Ideas', "
                            "'Faith Wrestled', 'Childhood Lagos'. Return ONLY the label, nothing else."
                        ),
                    },
                    {"role": "user", "content": f"Notes in this cluster:\n{sample_text}"},
                ],
                max_tokens=20,
                temperature=0.5,
            )
            label = response.choices[0].message.content.strip().strip('"\'')
        except Exception as e:
            label = f"Cluster {cluster_id + 1}"
            print(f"    Warning: labeling failed for cluster {cluster_id}: {e}")

        cluster_labels.append(label)
        count = len(cluster_notes)
        print(f"    [{cluster_id:2d}] {label} ({count} notes)")

    return cluster_labels


def generate_topic_map(force: bool = False, on_progress=None) -> dict:
    """
    Full pipeline: load → cluster → reduce → label → save.

    Args:
        force: Regenerate even if topic_map.json exists.
        on_progress: Optional callback(step, total_steps, message).

    Returns:
        The topic map dict.
    """
    if not force and TOPIC_MAP_FILE.exists():
        # Check if topic map is newer than embeddings
        map_mtime = TOPIC_MAP_FILE.stat().st_mtime
        emb_mtime = EMBEDDINGS_FILE.stat().st_mtime
        if map_mtime > emb_mtime:
            print("Topic map is up-to-date. Use --force to regenerate.")
            with open(TOPIC_MAP_FILE, encoding="utf-8") as f:
                return json.load(f)

    start = time.time()

    def _progress(step, total, msg):
        print(f"  Step {step}/{total}: {msg}")
        if on_progress:
            on_progress(step, total, msg)

    _progress(1, 5, "Loading index")
    embeddings, metadata = load_index()
    print(f"    {len(metadata)} notes, {embeddings.shape[1]}D embeddings")

    _progress(2, 5, "Finding optimal cluster count")
    k = find_optimal_k(embeddings)

    _progress(3, 5, "Clustering embeddings")
    labels, centroids = cluster_embeddings(embeddings, k)

    _progress(4, 5, "Projecting to 2D with UMAP")
    coords_2d = reduce_to_2d(embeddings)

    _progress(5, 5, "Labeling clusters with AI")
    cluster_labels = label_clusters(metadata, labels, k)

    # Compute 2D cluster centers (mean of member positions)
    cluster_centers_2d = []
    for cid in range(k):
        mask = labels == cid
        if mask.any():
            center = coords_2d[mask].mean(axis=0)
            cluster_centers_2d.append(center.tolist())
        else:
            cluster_centers_2d.append([0.5, 0.5])

    # Build the output
    topic_map = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note_count": len(metadata),
        "cluster_count": k,
        "clusters": [
            {
                "id": cid,
                "label": cluster_labels[cid],
                "color": _PALETTE[cid % len(_PALETTE)],
                "center": cluster_centers_2d[cid],
                "count": int((labels == cid).sum()),
            }
            for cid in range(k)
        ],
        "notes": [
            {
                "x": float(coords_2d[i][0]),
                "y": float(coords_2d[i][1]),
                "cluster": int(labels[i]),
                "title": metadata[i]["title"],
                "folder": metadata[i]["folder"],
                "id": metadata[i]["id"],
            }
            for i in range(len(metadata))
        ],
    }

    # Save
    INDEX_DIR.mkdir(exist_ok=True)
    with open(TOPIC_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(topic_map, f, ensure_ascii=False)

    elapsed = time.time() - start
    print(f"\nDone. {k} clusters, {len(metadata)} notes mapped in {elapsed:.1f}s")
    print(f"Saved to {TOPIC_MAP_FILE}")

    return topic_map


if __name__ == "__main__":
    force = "--force" in sys.argv
    generate_topic_map(force=force)
