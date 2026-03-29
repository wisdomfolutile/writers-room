"""
Writers Room — Mind Constellation

Generates a 2D topic map from note embeddings using UMAP + K-means.
Clusters are auto-labeled via the user's BYOK provider. Output is saved as
index/topic_map.json for the Swift app to visualize.

Usage:
    python3 topic_map.py              # generate/update topic map
    python3 topic_map.py --force      # regenerate from scratch
"""

import colorsys
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

# Use stderr for diagnostics so stdout stays clean for the bridge protocol
_log = lambda msg: print(msg, file=sys.stderr, flush=True)

# Load .env in dev / standalone CLI
if os.environ.get("WRITERSROOM_DEV") or __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")

INDEX_DIR = Path(__file__).parent / "index"
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
METADATA_FILE = INDEX_DIR / "metadata.json"
TOPIC_MAP_FILE = INDEX_DIR / "topic_map.json"


# ---------------------------------------------------------------------------
# Color generation
# ---------------------------------------------------------------------------

def _generate_palette(n: int) -> list[str]:
    """Generate n perceptually distinct colors using golden-angle HSL spacing.

    The golden angle (137.508 degrees) maximizes angular separation between
    consecutive hues. Saturation and lightness are varied per index to avoid
    perceptual collisions even when hues are close.
    """
    golden_angle = 137.508
    colors = []
    for i in range(n):
        hue = (i * golden_angle) % 360
        saturation = 0.65 + 0.20 * ((i % 3) / 2)       # 0.65 – 0.85
        lightness = 0.55 + 0.15 * (((i + 1) % 3) / 2)  # 0.55 – 0.70
        r, g, b = colorsys.hls_to_rgb(hue / 360, lightness, saturation)
        colors.append(f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}")
    return colors


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------

def load_index() -> tuple[np.ndarray, list[dict]]:
    """Load embeddings and metadata from disk."""
    embeddings = np.load(EMBEDDINGS_FILE)
    with open(METADATA_FILE, encoding="utf-8") as f:
        metadata = json.load(f)
    return embeddings, metadata


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def find_optimal_k(embeddings: np.ndarray) -> int:
    """Find optimal cluster count using a composite of three metrics:
    silhouette (40%), inverted Davies-Bouldin (30%), Calinski-Harabasz (30%).
    """
    from sklearn.cluster import KMeans
    from sklearn.metrics import (
        calinski_harabasz_score,
        davies_bouldin_score,
        silhouette_score,
    )

    n = len(embeddings)
    sqrt_n = int(np.sqrt(n))
    k_min = max(8, sqrt_n // 4)
    k_max = max(k_min + 5, min(50, sqrt_n))
    k_range = range(k_min, k_max + 1)

    _log(f"  Finding optimal k in range {k_min}–{k_max} ({n} notes)...")

    scores = []
    sample_size = min(3000, n)

    for k in k_range:
        km = KMeans(n_clusters=k, n_init=20, init="k-means++", random_state=42, max_iter=300)
        labels = km.fit_predict(embeddings)

        sil = silhouette_score(embeddings, labels, sample_size=sample_size)
        db = davies_bouldin_score(embeddings, labels)
        ch = calinski_harabasz_score(embeddings, labels)

        scores.append((k, sil, db, ch))
        _log(f"    k={k:2d}  sil={sil:.4f}  db={db:.4f}  ch={ch:.1f}")

    # Normalize each metric to [0, 1]
    def _normalize(vals):
        lo, hi = min(vals), max(vals)
        return [(v - lo) / (hi - lo) if hi > lo else 0.5 for v in vals]

    sil_norm = _normalize([s[1] for s in scores])
    db_norm = [1.0 - v for v in _normalize([s[2] for s in scores])]  # lower DB is better
    ch_norm = _normalize([s[3] for s in scores])

    best_k, best_composite = k_range.start, -1
    for i, (k, _, _, _) in enumerate(scores):
        composite = 0.4 * sil_norm[i] + 0.3 * db_norm[i] + 0.3 * ch_norm[i]
        if composite > best_composite:
            best_composite = composite
            best_k = k

    _log(f"  Best: k={best_k} (composite={best_composite:.4f})")
    return best_k


def cluster_embeddings(embeddings: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Run K-means clustering. Returns (labels, centroids)."""
    from sklearn.cluster import KMeans

    _log(f"  Clustering into {k} groups...")
    km = KMeans(n_clusters=k, n_init=20, init="k-means++", random_state=42, max_iter=300)
    labels = km.fit_predict(embeddings)
    return labels, km.cluster_centers_


# ---------------------------------------------------------------------------
# UMAP dimensionality reduction
# ---------------------------------------------------------------------------

def reduce_to_2d(embeddings: np.ndarray) -> np.ndarray:
    """Project embeddings to 2D via UMAP."""
    import umap

    _log(f"  UMAP: {embeddings.shape[0]} points, {embeddings.shape[1]}D → 2D...")
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=30,
        min_dist=0.3,
        metric="cosine",
        random_state=42,
        verbose=False,
    )
    coords_2d = reducer.fit_transform(embeddings)

    # Normalize to [0, 1]
    mins = coords_2d.min(axis=0)
    maxs = coords_2d.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1
    coords_2d = (coords_2d - mins) / ranges

    return coords_2d


# ---------------------------------------------------------------------------
# Cluster labeling (BYOK-aware)
# ---------------------------------------------------------------------------

def label_clusters(
    metadata: list[dict],
    labels: np.ndarray,
    k: int,
    provider_id: str | None = None,
    api_key: str | None = None,
) -> list[str]:
    """Generate human-readable labels for each cluster via the user's AI provider.

    Each label is informed by the labels already assigned, preventing duplicates
    and contradictions. Uses diverse note sampling (longest + newest + random).
    """
    if provider_id and api_key:
        from providers import get_synthesis_client
        client, model = get_synthesis_client(provider_id, api_key)
    else:
        from openai import OpenAI
        client = OpenAI()
        model = "gpt-4o-mini"

    cluster_labels = []
    _log(f"  Labeling {k} clusters via {model}...")

    for cluster_id in range(k):
        cluster_notes = [
            (i, metadata[i])
            for i in range(len(metadata))
            if labels[i] == cluster_id
        ]

        # Diverse sampling: 5 longest + 5 most recent + 5 random
        by_length = sorted(cluster_notes, key=lambda x: len(x[1].get("content", "")), reverse=True)
        by_recency = sorted(cluster_notes, key=lambda x: x[1].get("modified", ""), reverse=True)

        seen_ids = set()
        sample = []
        for source in [by_length[:5], by_recency[:5]]:
            for item in source:
                if item[0] not in seen_ids and len(sample) < 15:
                    sample.append(item)
                    seen_ids.add(item[0])

        # Fill remaining with random picks
        import random
        remaining = [n for n in cluster_notes if n[0] not in seen_ids]
        random.shuffle(remaining)
        for item in remaining[:15 - len(sample)]:
            sample.append(item)

        sample_text = "\n".join(
            f"- [{m['folder']}] {m['title']}: {m.get('content', '')[:200]}"
            for _, m in sample
        )

        # Include already-assigned labels so the model avoids duplicates
        existing = ", ".join(cluster_labels) if cluster_labels else "(none yet)"

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are labeling a cluster of a writer's personal notes. "
                            "Given sample notes from the cluster, generate a short, evocative label "
                            "(2-4 words) that captures the theme. Be specific and poetic, not generic. "
                            "Examples: 'Nigerian Identity', 'Love & Longing', 'Startup Ideas', "
                            "'Faith Wrestled', 'Childhood Lagos'.\n\n"
                            f"Labels already assigned to other clusters: {existing}\n"
                            "Your label MUST be unique and distinct from all of the above. "
                            "Return ONLY the label, nothing else."
                        ),
                    },
                    {"role": "user", "content": f"Notes in this cluster:\n{sample_text}"},
                ],
                max_tokens=20,
                temperature=0.5,
                timeout=15,
            )
            label = response.choices[0].message.content.strip().strip('"\'')
        except Exception as e:
            # Fast-fail on auth errors
            err_type = type(e).__name__
            if "auth" in err_type.lower() or "permission" in err_type.lower():
                raise RuntimeError(f"API key invalid for {model}: {e}") from e
            label = f"Cluster {cluster_id + 1}"
            _log(f"    Warning: labeling failed for cluster {cluster_id}: {e}")

        cluster_labels.append(label)
        count = len(cluster_notes)
        _log(f"    [{cluster_id:2d}] {label} ({count} notes)")

    return cluster_labels


# ---------------------------------------------------------------------------
# Bridges: cross-cluster semantic connections
# ---------------------------------------------------------------------------

def find_bridges(
    embeddings: np.ndarray,
    labels: np.ndarray,
    coords_2d: np.ndarray,
    metadata: list[dict],
    n_bridges: int = 20,
) -> list[dict]:
    """Find notes that are semantically close to a different cluster.

    These are the user's most original cross-pollination ideas.
    Returns the top n_bridges pairs sorted by similarity.
    """
    from sklearn.metrics.pairwise import cosine_similarity

    _log(f"  Finding top {n_bridges} cross-cluster bridges...")

    n = len(embeddings)
    # Sample to keep computation reasonable (full pairwise on 10k notes = 100M pairs)
    max_sample = min(n, 3000)
    if n > max_sample:
        rng = np.random.RandomState(42)
        sample_idx = rng.choice(n, max_sample, replace=False)
    else:
        sample_idx = np.arange(n)

    sample_emb = embeddings[sample_idx]
    sim_matrix = cosine_similarity(sample_emb)

    bridges = []
    for local_i in range(len(sample_idx)):
        global_i = sample_idx[local_i]
        cluster_i = labels[global_i]

        # Find most similar note in a different cluster
        best_sim, best_j = -1, -1
        for local_j in range(len(sample_idx)):
            global_j = sample_idx[local_j]
            if labels[global_j] == cluster_i:
                continue
            if sim_matrix[local_i, local_j] > best_sim:
                best_sim = sim_matrix[local_i, local_j]
                best_j = global_j

        if best_j >= 0:
            bridges.append({
                "from_idx": int(global_i),
                "to_idx": int(best_j),
                "similarity": float(best_sim),
                "from_cluster": int(cluster_i),
                "to_cluster": int(labels[best_j]),
            })

    # Take top n_bridges by similarity, deduplicate (keep the stronger direction)
    bridges.sort(key=lambda b: b["similarity"], reverse=True)
    seen_pairs = set()
    top_bridges = []
    for b in bridges:
        pair = (min(b["from_idx"], b["to_idx"]), max(b["from_idx"], b["to_idx"]))
        if pair not in seen_pairs and b["from_cluster"] != b["to_cluster"]:
            seen_pairs.add(pair)
            top_bridges.append({
                "from": {
                    "x": float(coords_2d[b["from_idx"]][0]),
                    "y": float(coords_2d[b["from_idx"]][1]),
                    "cluster": b["from_cluster"],
                    "title": metadata[b["from_idx"]]["title"],
                },
                "to": {
                    "x": float(coords_2d[b["to_idx"]][0]),
                    "y": float(coords_2d[b["to_idx"]][1]),
                    "cluster": b["to_cluster"],
                    "title": metadata[b["to_idx"]]["title"],
                },
                "strength": float(b["similarity"]),
            })
            if len(top_bridges) >= n_bridges:
                break

    _log(f"    Found {len(top_bridges)} bridges (top similarity: {top_bridges[0]['strength']:.3f})")
    return top_bridges


# ---------------------------------------------------------------------------
# Mind Profile: intellectual identity portrait
# ---------------------------------------------------------------------------

def generate_mind_profile(
    clusters: list[dict],
    bridges: list[dict],
    note_count: int,
    provider_id: str | None = None,
    api_key: str | None = None,
) -> str:
    """Generate a one-paragraph intellectual portrait from cluster distribution."""
    if provider_id and api_key:
        from providers import get_synthesis_client
        client, model = get_synthesis_client(provider_id, api_key)
    else:
        from openai import OpenAI
        client = OpenAI()
        model = "gpt-4o-mini"

    # Build the profile prompt with cluster stats
    sorted_clusters = sorted(clusters, key=lambda c: c["count"], reverse=True)
    cluster_breakdown = "\n".join(
        f"- {c['label']}: {c['count']} notes ({c['count'] * 100 // note_count}%)"
        for c in sorted_clusters
    )

    # Summarize strongest bridges
    bridge_summary = "\n".join(
        f"- Bridge between '{b['from']['title'][:50]}' ({b['from']['cluster']}) "
        f"and '{b['to']['title'][:50]}' ({b['to']['cluster']}) "
        f"(similarity: {b['strength']:.2f})"
        for b in bridges[:8]
    ) if bridges else "(no bridges)"

    # Map cluster IDs to labels for bridge context
    id_to_label = {c["id"]: c["label"] for c in clusters}
    bridge_cluster_summary = []
    from collections import Counter
    bridge_pairs = Counter()
    for b in bridges:
        pair = tuple(sorted([
            id_to_label.get(b["from"]["cluster"], "?"),
            id_to_label.get(b["to"]["cluster"], "?"),
        ]))
        bridge_pairs[pair] += 1
    for (a, b), count in bridge_pairs.most_common(5):
        bridge_cluster_summary.append(f"- {a} <-> {b}: {count} bridges")

    _log(f"  Generating mind profile via {model}...")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are writing a one-paragraph intellectual portrait of a writer "
                        "based on how their notes cluster thematically. You have their cluster "
                        "distribution (what they think about most) and their cross-cluster bridges "
                        "(where their ideas unexpectedly connect).\n\n"
                        "Write in second person ('You are...'). Be specific, warm, and insightful. "
                        "Name the actual cluster themes. Highlight what makes their thinking distinctive "
                        "based on the bridges between clusters. Keep it to 3-4 sentences. "
                        "Do not use em dashes. Do not be generic."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Total notes: {note_count}\n\n"
                        f"Cluster distribution:\n{cluster_breakdown}\n\n"
                        f"Strongest cross-cluster connections:\n{''.join(bridge_cluster_summary) or bridge_summary}\n"
                    ),
                },
            ],
            max_tokens=200,
            temperature=0.7,
            timeout=15,
        )
        profile = response.choices[0].message.content.strip()
    except Exception as e:
        _log(f"    Warning: mind profile generation failed: {e}")
        profile = ""

    if profile:
        _log(f"    Profile: {profile[:80]}...")
    return profile


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def generate_topic_map(
    force: bool = False,
    on_progress=None,
    provider_id: str | None = None,
    api_key: str | None = None,
) -> dict:
    """
    Full pipeline: load -> cluster -> reduce -> label -> save.

    Returns the topic map dict.
    """
    if not force and TOPIC_MAP_FILE.exists():
        map_mtime = TOPIC_MAP_FILE.stat().st_mtime
        emb_mtime = EMBEDDINGS_FILE.stat().st_mtime
        if map_mtime > emb_mtime:
            _log("Topic map is up-to-date. Use --force to regenerate.")
            with open(TOPIC_MAP_FILE, encoding="utf-8") as f:
                return json.load(f)

    start = time.time()

    def _progress(step, total, msg):
        _log(f"  Step {step}/{total}: {msg}")
        if on_progress:
            on_progress(step, total, msg)

    total_steps = 7

    _progress(1, total_steps, "Loading index")
    embeddings, metadata = load_index()
    _log(f"    {len(metadata)} notes, {embeddings.shape[1]}D embeddings")

    _progress(2, total_steps, "Finding optimal cluster count")
    k = find_optimal_k(embeddings)

    _progress(3, total_steps, "Clustering embeddings")
    labels, centroids = cluster_embeddings(embeddings, k)

    _progress(4, total_steps, "Projecting to 2D with UMAP")
    coords_2d = reduce_to_2d(embeddings)

    _progress(5, total_steps, "Labeling clusters with AI")
    cluster_labels = label_clusters(metadata, labels, k, provider_id=provider_id, api_key=api_key)

    # Generate perceptually distinct colors for exactly k clusters
    palette = _generate_palette(k)

    # Compute 2D cluster centers (mean of member positions)
    cluster_centers_2d = []
    for cid in range(k):
        mask = labels == cid
        if mask.any():
            center = coords_2d[mask].mean(axis=0)
            cluster_centers_2d.append(center.tolist())
        else:
            cluster_centers_2d.append([0.5, 0.5])

    clusters_data = [
        {
            "id": cid,
            "label": cluster_labels[cid],
            "color": palette[cid],
            "center": cluster_centers_2d[cid],
            "count": int((labels == cid).sum()),
        }
        for cid in range(k)
    ]

    _progress(6, total_steps, "Finding cross-cluster bridges")
    bridges = find_bridges(embeddings, labels, coords_2d, metadata)

    _progress(7, total_steps, "Generating mind profile")
    mind_profile = generate_mind_profile(
        clusters_data, bridges, len(metadata),
        provider_id=provider_id, api_key=api_key,
    )

    topic_map = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note_count": len(metadata),
        "cluster_count": k,
        "mind_profile": mind_profile,
        "clusters": clusters_data,
        "bridges": bridges,
        "notes": [
            {
                "x": float(coords_2d[i][0]),
                "y": float(coords_2d[i][1]),
                "cluster": int(labels[i]),
                "title": metadata[i]["title"],
                "folder": metadata[i]["folder"],
                "id": metadata[i]["id"],
                "created": metadata[i].get("created", ""),
            }
            for i in range(len(metadata))
        ],
    }

    # Atomic write: temp file + rename
    INDEX_DIR.mkdir(exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(INDEX_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(topic_map, f, ensure_ascii=False)
        os.replace(tmp_path, str(TOPIC_MAP_FILE))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    elapsed = time.time() - start
    _log(f"\nDone. {k} clusters, {len(metadata)} notes mapped in {elapsed:.1f}s")
    _log(f"Saved to {TOPIC_MAP_FILE}")

    return topic_map


# ---------------------------------------------------------------------------
# Cluster deep-dive: sub-clustering within a single cluster
# ---------------------------------------------------------------------------

def generate_sub_map(
    cluster_id: int,
    on_progress=None,
    provider_id: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Run secondary clustering within a single cluster for deep-dive view."""

    def _progress(step, total, msg):
        _log(f"  Sub-map step {step}/{total}: {msg}")
        if on_progress:
            on_progress(step, total, msg)

    _progress(1, 4, "Loading index")
    embeddings, metadata = load_index()

    # Load the existing topic map to get cluster assignments
    if not TOPIC_MAP_FILE.exists():
        raise RuntimeError("Topic map not generated yet. Generate the main map first.")

    with open(TOPIC_MAP_FILE, encoding="utf-8") as f:
        main_map = json.load(f)

    # Find which notes belong to this cluster
    note_indices = [
        i for i, n in enumerate(main_map["notes"])
        if n["cluster"] == cluster_id
    ]

    if len(note_indices) < 4:
        raise RuntimeError(f"Cluster {cluster_id} has too few notes ({len(note_indices)}) for sub-clustering.")

    cluster_embeddings = embeddings[note_indices]
    cluster_metadata = [metadata[i] for i in note_indices]
    cluster_label = next(
        (c["label"] for c in main_map["clusters"] if c["id"] == cluster_id),
        f"Cluster {cluster_id}"
    )

    _log(f"  Sub-clustering '{cluster_label}' ({len(note_indices)} notes)...")

    _progress(2, 4, f"Clustering within '{cluster_label}'")
    # Determine sub-k based on cluster size
    n = len(note_indices)
    sub_k = max(3, min(10, int(np.sqrt(n) / 2)))

    from sklearn.cluster import KMeans
    km = KMeans(n_clusters=sub_k, n_init=20, init="k-means++", random_state=42, max_iter=300)
    sub_labels = km.fit_predict(cluster_embeddings)

    _progress(3, 4, "Projecting to 2D")
    import umap
    reducer = umap.UMAP(
        n_components=2, n_neighbors=min(15, n - 1),
        min_dist=0.2, metric="cosine", random_state=42, verbose=False,
    )
    coords_2d = reducer.fit_transform(cluster_embeddings)
    mins = coords_2d.min(axis=0)
    maxs = coords_2d.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1
    coords_2d = (coords_2d - mins) / ranges

    _progress(4, 4, "Labeling sub-themes")
    sub_labels_text = label_clusters(
        cluster_metadata, sub_labels, sub_k,
        provider_id=provider_id, api_key=api_key,
    )

    palette = _generate_palette(sub_k)

    # Compute centers
    centers = []
    for cid in range(sub_k):
        mask = sub_labels == cid
        if mask.any():
            centers.append(coords_2d[mask].mean(axis=0).tolist())
        else:
            centers.append([0.5, 0.5])

    sub_map = {
        "parent_cluster_id": cluster_id,
        "parent_cluster_label": cluster_label,
        "note_count": len(note_indices),
        "cluster_count": sub_k,
        "clusters": [
            {
                "id": cid,
                "label": sub_labels_text[cid],
                "color": palette[cid],
                "center": centers[cid],
                "count": int((sub_labels == cid).sum()),
            }
            for cid in range(sub_k)
        ],
        "notes": [
            {
                "x": float(coords_2d[i][0]),
                "y": float(coords_2d[i][1]),
                "cluster": int(sub_labels[i]),
                "title": cluster_metadata[i]["title"],
                "folder": cluster_metadata[i]["folder"],
                "id": cluster_metadata[i]["id"],
                "created": cluster_metadata[i].get("created", ""),
            }
            for i in range(len(cluster_metadata))
        ],
    }

    _log(f"  Sub-map: {sub_k} sub-themes in '{cluster_label}'")
    return sub_map


if __name__ == "__main__":
    force = "--force" in sys.argv
    generate_topic_map(force=force)
