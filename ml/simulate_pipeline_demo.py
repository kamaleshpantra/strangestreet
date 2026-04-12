#!/usr/bin/env python3
"""
Strange Street — In-memory ML pipeline simulation (no database).

Mirrors the real pipeline conceptually:
  1) Graph: follower graph → PageRank, Louvain communities, friend-of-friend
  2) Features: synthetic post embeddings + user centroids + interest SVD
  3) Feed: interaction matrix → TruncatedSVD → scores + recency blend + re-rank
  4) People: weighted blend (FoF, PageRank, community, Jaccard, topic cosine)
  5) Zones: interest + semantic + activity blend (simplified)
  6) Safety: same regex heuristic as ml/safety.py
  7) Evaluation: Precision@K, coverage, diversity
  8) Bandits: Real-Time Reinforcement Learning UCB sorting

Run from repo root:
    python ml/simulate_pipeline_demo.py
    python ml/simulate_pipeline_demo.py --large
    python ml/simulate_pipeline_demo.py --users 8000 --posts 25000 --follows 120000 --interactions 600000
    python ml/simulate_pipeline_demo.py --real-embeddings   # not recommended with --large (too slow)

Embeddings: default uses small random normalized vectors (fast, full print).
With --real-embeddings, uses all-MiniLM-L6-v2 on short synthetic post texts (384-d;
only first 12 dims printed per line for readability).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

import numpy as np

# ── Optional: real embeddings (same model as production) ─────────────────
def _try_real_embeddings(post_texts: List[str]) -> np.ndarray | None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return model.encode(post_texts, batch_size=8, show_progress_bar=False)


# ── Safety patterns (aligned with ml/safety.py) ────────────────────────────
TOXIC_PATTERNS = [
    r"\b(kill|murder|attack)\b.*\b(you|them|her|him)\b",
    r"\b(hate|despise)\b.*\b(you|them|people|everyone)\b",
    r"\b(stupid|idiot|moron|dumb)\b",
    r"\b(racist|sexist|homophobic)\b",
    r"\bdie\b.*\b(in a|you should)\b",
]
SPAM_PATTERNS = [
    r"(buy now|click here|free money|make \$\d+)",
    r"(DM me for|check my bio|link in bio)",
    r"(.)\1{5,}",
    r"https?://\S+.*https?://\S+",
]


def score_toxicity(text: str) -> float:
    if not text:
        return 0.0
    text_lower = text.lower()
    hits = 0.0
    for pattern in TOXIC_PATTERNS:
        if re.search(pattern, text_lower):
            hits += 1
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text_lower):
            hits += 0.5
    total_patterns = len(TOXIC_PATTERNS) + len(SPAM_PATTERNS)
    return min(hits / max(total_patterns * 0.3, 1), 1.0)


def print_vec(name: str, v: np.ndarray, head: int = 12) -> None:
    v = np.asarray(v, dtype=float).ravel()
    shown = v[: min(head, len(v))]
    tail = f" ... (+{len(v) - head} dims)" if len(v) > head else ""
    print(f"    {name}: dim={len(v)}  head=[{', '.join(f'{x:.4f}' for x in shown)}]{tail}")


def normalize_rows(X: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return X / norms


# ── Synthetic world ─────────────────────────────────────────────────────────
@dataclass
class SimUser:
    id: int
    name: str
    interests: Set[int]  # interest ids 0..I-1


@dataclass
class SimPost:
    id: int
    author_id: int
    content: str
    category: str
    age_days: int


@dataclass
class SimInteraction:
    user_id: int
    post_id: int
    action: str
    weight: float


def build_synthetic_world(rng: np.random.Generator) -> Tuple[
    List[SimUser],
    List[SimPost],
    List[Tuple[int, int]],  # follows: follower -> followed
    List[SimInteraction],
    List[Tuple[int, int]],  # zone_id, user_id memberships
    Dict[int, List[int]],  # zone_id -> post_ids in zone
]:
    """Small but structured toy world."""
    users = [
        SimUser(1, "alice", {0, 1, 2}),
        SimUser(2, "bob", {1, 2, 3}),
        SimUser(3, "carol", {0, 3}),
        SimUser(4, "dave", {2, 4}),
        SimUser(5, "erin", {1, 4}),
        SimUser(6, "frank", {0, 1}),  # sparse — good for FoF / inference demos
    ]
    posts = [
        SimPost(101, 1, "Loving rust and systems programming lately", "technology", 1),
        SimPost(102, 2, "Coffee meetup this weekend downtown", "food", 3),
        SimPost(103, 1, "New grad internship tips for interviews", "technology", 2),
        SimPost(104, 3, "Hiking trail photos from Sunday", "travel", 8),
        SimPost(105, 4, "Buy now click here free money $999", "general", 0),  # spammy
        SimPost(106, 2, "Machine learning study group notes", "technology", 4),
        SimPost(107, 5, "You are stupid and dumb", "general", 1),  # toxic
        SimPost(108, 6, "Anyone into photography and film?", "art", 6),
    ]
    follows = [
        (1, 2),
        (1, 3),
        (2, 1),
        (2, 4),
        (3, 1),
        (4, 2),
        (5, 2),
        (5, 3),
        (6, 1),
        (6, 2),
    ]
    interactions = [
        SimInteraction(1, 101, "like", 1.0),
        SimInteraction(1, 103, "comment", 2.0),
        SimInteraction(1, 106, "view", 0.1),
        SimInteraction(2, 101, "view", 0.1),
        SimInteraction(2, 106, "like", 1.0),
        SimInteraction(3, 104, "like", 1.0),
        SimInteraction(4, 102, "comment", 2.0),
        SimInteraction(5, 103, "like", 1.0),
        SimInteraction(5, 106, "like", 1.0),
        SimInteraction(6, 108, "view", 0.1),
        SimInteraction(6, 101, "like", 1.0),
    ]
    # zone 0: tech-ish members 1,2,6 posts 101,103,106
    zone_memberships = [(0, 1), (0, 2), (0, 6)]
    zone_posts = {0: [101, 103, 106]}
    return users, posts, follows, interactions, zone_memberships, zone_posts


# ── Large synthetic world (scalable) ───────────────────────────────────────
@dataclass
class BigSimConfig:
    users: int = 5000
    posts: int = 15000
    num_follows: int = 80000
    num_interactions: int = 400000
    num_interests: int = 40
    zones: int = 25
    toxic_post_fraction: float = 0.008
    spam_post_fraction: float = 0.012


def build_large_synthetic_world(cfg: BigSimConfig, rng: np.random.Generator) -> Tuple[
    List[SimUser],
    List[SimPost],
    List[Tuple[int, int]],
    List[SimInteraction],
    List[Tuple[int, int]],
    Dict[int, List[int]],
]:
    """
    Generate a large, realistic-enough social graph + posts + implicit feedback.
    - Follows prefer users with overlapping interests (clustered graph).
    - Interactions bias toward posts from followed authors and same-topic authors.
    """
    U, P, I = cfg.users, cfg.posts, cfg.num_interests
    max_follow_edges = max(U * (U - 1), 0)
    num_follows_target = min(cfg.num_follows, max_follow_edges)
    if num_follows_target < cfg.num_follows:
        print(f"  [gen] capping follows {cfg.num_follows} -> {num_follows_target} (max directed edges)")

    categories = [
        "general", "technology", "sports", "news", "science",
        "gaming", "food", "travel", "music", "art",
    ]

    users: List[SimUser] = []
    for uid in range(1, U + 1):
        k = int(rng.integers(2, min(8, I) + 1))
        picks = rng.choice(np.arange(I, dtype=int), size=k, replace=False)
        users.append(SimUser(uid, f"user_{uid}", set(picks.tolist())))

    user_interest_arr = {u.id: u.interests for u in users}

    posts: List[SimPost] = []
    for pid in range(1, P + 1):
        author = int(rng.integers(1, U + 1))
        cat = str(rng.choice(categories))
        age_days = int(rng.integers(0, 90))
        body = f"{cat} discussion #{pid} by author {author} ref={int(rng.integers(0, 1_000_000))}"
        r = rng.random()
        if r < cfg.toxic_post_fraction:
            body = "You are stupid and dumb " + body
        elif r < cfg.toxic_post_fraction + cfg.spam_post_fraction:
            body = "Buy now click here free money $999 " + body
        posts.append(SimPost(pid, author, body, cat, age_days))

    post_by_id = {p.id: p for p in posts}
    author_posts: Dict[int, List[int]] = defaultdict(list)
    for p in posts:
        author_posts[p.author_id].append(p.id)

    # interest_id -> users who selected it (speeds up interaction generation)
    interest_to_users: Dict[int, List[int]] = defaultdict(list)
    for uid, ints in user_interest_arr.items():
        for ii in ints:
            interest_to_users[ii].append(uid)

    # --- follows: many edges, prefer interest overlap ---
    follows_set: Set[Tuple[int, int]] = set()
    max_attempts = max(num_follows_target * 40, 500_000)
    attempts = 0
    while len(follows_set) < num_follows_target and attempts < max_attempts:
        attempts += 1
        a = int(rng.integers(1, U + 1))
        if rng.random() < 0.45:
            mine = user_interest_arr[a]
            pool = [
                v for v in range(1, U + 1)
                if v != a and user_interest_arr[v] & mine
            ]
            if not pool:
                b = int(rng.integers(1, U + 1))
            else:
                b = int(rng.choice(pool))
        else:
            b = int(rng.integers(1, U + 1))
        if a != b:
            follows_set.add((a, b))
    follows = list(follows_set)

    followers_of: Dict[int, List[int]] = defaultdict(list)
    for x, y in follows:
        followers_of[y].append(x)

    # follower -> list of followed (for fast lookup)
    following_map: Dict[int, List[int]] = defaultdict(list)
    for a, b in follows:
        following_map[a].append(b)

    interactions: List[SimInteraction] = []
    for _ in range(cfg.num_interactions):
        u = int(rng.integers(1, U + 1))
        roll = rng.random()
        chosen_post: SimPost
        if roll < 0.42:
            fol = following_map.get(u, [])
            if fol:
                auth = int(rng.choice(fol))
                ap = author_posts.get(auth, [])
                chosen_post = post_by_id[int(rng.choice(ap))] if ap else rng.choice(posts)
            else:
                chosen_post = rng.choice(posts)
        elif roll < 0.72:
            mine = user_interest_arr[u]
            author_pool: Set[int] = set()
            for ii in mine:
                for v in interest_to_users.get(ii, []):
                    if v != u:
                        author_pool.add(v)
            author_pool = [a for a in author_pool if author_posts.get(a)]
            if author_pool:
                auth = int(rng.choice(author_pool))
                ap = author_posts[auth]
                chosen_post = post_by_id[int(rng.choice(ap))]
            else:
                chosen_post = rng.choice(posts)
        else:
            chosen_post = rng.choice(posts)

        ar = rng.random()
        if ar < 0.52:
            interactions.append(SimInteraction(u, chosen_post.id, "view", 0.1))
        elif ar < 0.82:
            interactions.append(SimInteraction(u, chosen_post.id, "like", 1.0))
        elif ar < 0.96:
            interactions.append(SimInteraction(u, chosen_post.id, "comment", 2.0))
        else:
            interactions.append(SimInteraction(u, chosen_post.id, "skip", -0.5))

    # --- zones: random memberships + posts tied to members ---
    zone_memberships: List[Tuple[int, int]] = []
    zone_posts: Dict[int, List[int]] = defaultdict(list)
    all_pids = np.array([p.id for p in posts], dtype=int)
    for z in range(cfg.zones):
        zsize = int(rng.integers(max(20, U // 200), max(21, U // 8)))
        zsize = min(zsize, U)
        members = rng.choice(np.arange(1, U + 1), size=zsize, replace=False)
        mset = set(int(x) for x in members.tolist())
        for m in mset:
            zone_memberships.append((z, m))
        n_zp = int(rng.integers(30, min(800, P // max(cfg.zones, 1) + 50)))
        for _ in range(n_zp):
            pid = int(rng.choice(all_pids))
            p = post_by_id[pid]
            if p.author_id in mset or rng.random() < 0.08:
                zone_posts[z].append(pid)
        zone_posts[z] = sorted(set(zone_posts[z]))[: max(n_zp, 40)]

    return users, posts, follows, interactions, zone_memberships, dict(zone_posts)


# ── 1) Graph engine (NetworkX) ─────────────────────────────────────────────
def run_graph_sim(
    user_ids: List[int],
    follows: List[Tuple[int, int]],
    user_interests: Dict[int, Set[int]],
    rng: np.random.Generator,
    *,
    quiet: bool = False,
    max_fof: int = 50,
    sample_print_users: int = 10,
) -> Dict[int, dict]:
    import networkx as nx

    print("\n" + "=" * 70)
    print("STEP 1 - GRAPH ENGINE (follower graph)")
    print("=" * 70)

    G = nx.DiGraph()
    G.add_nodes_from(user_ids)
    for a, b in follows:
        G.add_edge(a, b)
    print(f"  Nodes: {G.number_of_nodes()}  Edges (follows): {G.number_of_edges()}")
    if not quiet:
        print(f"  Edges (follower -> followed): {list(G.edges())}")
    else:
        samp = follows[: min(6, len(follows))]
        print(f"  Sample follows (first {len(samp)}): {samp}")

    t0 = time.perf_counter()
    if G.number_of_edges() == 0:
        pagerank = {n: 1.0 / len(user_ids) for n in user_ids}
    else:
        pr = nx.pagerank(G, alpha=0.85, max_iter=100)
        mx = max(pr.values()) or 1.0
        pagerank = {u: pr[u] / mx for u in user_ids}
    print(f"  PageRank wall time: {time.perf_counter() - t0:.3f}s")

    if quiet:
        pr_vals = np.array(list(pagerank.values()))
        print(
            f"  PageRank summary: min={pr_vals.min():.6f} max={pr_vals.max():.6f} "
            f"mean={pr_vals.mean():.6f} median={np.median(pr_vals):.6f}"
        )
        su = sorted(user_ids)[:sample_print_users]
        print(f"  Sample PageRank (users {su}):")
        for uid in su:
            print(f"    user {uid}: {pagerank[uid]:.6f}")
    else:
        print("\n  PageRank (normalized 0-1, higher = more influence in follow graph):")
        for uid in sorted(pagerank.keys()):
            print(f"    user {uid}: {pagerank[uid]:.6f}")

    partition = {u: -1 for u in user_ids}
    try:
        from community import community_louvain

        Gu = G.to_undirected()
        isolates = list(nx.isolates(Gu))
        Gc = Gu.copy()
        Gc.remove_nodes_from(isolates)
        if Gc.number_of_nodes() >= 3:
            t1 = time.perf_counter()
            part = community_louvain.best_partition(Gc, random_state=int(rng.integers(1 << 30)))
            print(f"  Louvain wall time: {time.perf_counter() - t1:.3f}s")
            for n in isolates:
                part[n] = -1
            partition = {u: part.get(u, -1) for u in user_ids}
            comm_counts = Counter(partition.values())
            print(f"  Louvain: {len(comm_counts)} community labels (including -1 isolates)")
            if quiet:
                topc = comm_counts.most_common(8)
                print(f"  Largest communities (id, count): {topc}")
            else:
                print("\n  Louvain communities (per user):")
                for uid in sorted(partition.keys()):
                    print(f"    user {uid}: community_id = {partition[uid]}")
        else:
            print("\n  Louvain: too few connected nodes - all community_id = -1")
    except Exception as e:
        print(f"\n  Louvain skipped: {e}")

    fof_map: Dict[int, Set[int]] = {}
    t2 = time.perf_counter()
    for node in G.nodes():
        direct = set(G.successors(node))
        fof: Set[int] = set()
        for f in direct:
            fof.update(G.successors(f))
        fof.discard(node)
        fof -= direct
        if len(fof) > max_fof:
            fof_list = list(fof)
            pick = rng.choice(len(fof_list), size=max_fof, replace=False)
            fof = set(fof_list[i] for i in pick)
        fof_map[node] = fof
    print(f"  Friend-of-friend (capped {max_fof}/user) wall time: {time.perf_counter() - t2:.3f}s")

    if quiet:
        fof_sizes = [len(v) for v in fof_map.values()]
        print(
            f"  FoF set sizes: min={min(fof_sizes)} max={max(fof_sizes)} "
            f"mean={np.mean(fof_sizes):.1f}"
        )
        su = sorted(user_ids)[:sample_print_users]
        print(f"  Sample FoF (users {su}):")
        for uid in su:
            print(f"    user {uid}: {sorted(fof_map[uid])[:20]}{'...' if len(fof_map[uid]) > 20 else ''}")
    else:
        print("\n  Friend-of-friend sets (2-hop along out-edges, excluding direct follows):")
        for uid in sorted(fof_map.keys()):
            print(f"    user {uid}: {sorted(fof_map[uid])}")

    # Sparse interest inference (like graph_engine.infer_interests)
    min_i = 3
    inferred: Dict[int, List[int]] = {}
    for uid in user_ids:
        if len(user_interests.get(uid, set())) >= min_i:
            continue
        neigh_counts: Counter = Counter()
        for n in list(G.predecessors(uid)) + list(G.successors(uid)):
            for iid in user_interests.get(n, set()):
                neigh_counts[iid] += 1
        existing = user_interests.get(uid, set())
        candidates = [(i, c) for i, c in neigh_counts.items() if i not in existing]
        candidates.sort(key=lambda x: -x[1])
        if candidates:
            inferred[uid] = [i for i, _ in candidates[:5]]

    if inferred:
        if quiet:
            print(f"  Inferred interests for {len(inferred)} sparse profiles (hidden); sample:")
            for uid in sorted(inferred.keys())[:5]:
                print(f"    user {uid}: interest_ids {inferred[uid]}")
        else:
            print("\n  Inferred interests for sparse profiles (neighbor frequency, top 5):")
            for uid, ids in sorted(inferred.items()):
                print(f"    user {uid}: interest_ids {ids}")
    else:
        print("\n  No sparse profiles for inference demo (all have >=3 interests).")

    out = {}
    for uid in user_ids:
        out[uid] = {
            "pagerank": pagerank[uid],
            "community_id": partition[uid],
            "degree": G.degree(uid),
            "fof_set": fof_map[uid],
            "inferred_interests": inferred.get(uid, []),
        }
    return out


# ── 2) Feature engine (embeddings) ──────────────────────────────────────────
def run_feature_sim(
    posts: List[SimPost],
    user_ids: List[int],
    user_interests: Dict[int, Set[int]],
    interest_dim: int,
    rng: np.random.Generator,
    real_embeddings: bool,
    *,
    quiet: bool = False,
    embedding_dim: int = 16,
    sample_print_posts: int = 5,
    sample_print_users: int = 8,
) -> Tuple[Dict[int, np.ndarray], Dict[int, np.ndarray], Dict[int, np.ndarray]]:
    print("\n" + "=" * 70)
    print("STEP 2 - FEATURE ENGINE (post embeddings -> user centroids + interest SVD)")
    print("=" * 70)

    texts = [p.content for p in posts]
    post_ids = [p.id for p in posts]
    n_posts = len(posts)

    if real_embeddings and n_posts > 2000:
        print("  --real-embeddings disabled for large post count (use synthetic).")
        real_embeddings = False

    if real_embeddings:
        emb = _try_real_embeddings(texts)
        if emb is None:
            print("  sentence-transformers not available - falling back to synthetic vectors.")
            real_embeddings = False

    t0 = time.perf_counter()
    if not real_embeddings:
        dim = embedding_dim
        print(
            f"  Using synthetic normalized embeddings (dim={dim}) - production uses 384-d MiniLM."
        )
        emb = np.zeros((n_posts, dim), dtype=np.float64)
        for j, p in enumerate(posts):
            rng_p = np.random.default_rng(1_000_000 + int(p.id))
            emb[j] = rng_p.standard_normal(dim)
        emb = normalize_rows(emb)
    else:
        print("  Using SentenceTransformer all-MiniLM-L6-v2 (384-d).")
    print(f"  Embedding matrix built in {time.perf_counter() - t0:.3f}s  shape={emb.shape}")

    post_emb = {pid: emb[i] for i, pid in enumerate(post_ids)}

    if quiet:
        norms = np.linalg.norm(emb, axis=1)
        print(
            f"  Post embedding norms: min={norms.min():.4f} max={norms.max():.4f} mean={norms.mean():.4f}"
        )
        for p in posts[:sample_print_posts]:
            print(f"    Post {p.id} @{p.author_id} [{p.category}] {p.content[:48]}...")
            print_vec("      embedding", post_emb[p.id], head=12)
    else:
        print("\n  Post embeddings (truncated print):")
        for p in posts:
            print(f"    Post {p.id} @{p.author_id} [{p.category}] {p.content[:50]}...")
            print_vec("      embedding", post_emb[p.id], head=12)

    # User centroid = mean of author's posts' embeddings (matches feature_engine idea)
    by_author: Dict[int, List[int]] = defaultdict(list)
    for p in posts:
        by_author[p.author_id].append(p.id)
    user_emb: Dict[int, np.ndarray] = {}
    zero = np.zeros(emb.shape[1], dtype=np.float64)
    for uid in user_ids:
        pids = by_author.get(uid, [])
        if pids:
            user_emb[uid] = np.mean([post_emb[pid] for pid in pids], axis=0)
        else:
            user_emb[uid] = zero.copy()

    if quiet:
        print(f"  User semantic profiles: {len(user_emb)} users")
        print(f"  Sample user vectors (users {sorted(user_ids)[:sample_print_users]}):")
        for uid in sorted(user_ids)[:sample_print_users]:
            print_vec(f"    user {uid}", user_emb[uid], head=12)
    else:
        print("\n  User semantic profile vectors (mean of own posts):")
        for uid in sorted(user_emb.keys()):
            print_vec(f"    user {uid}", user_emb[uid], head=12)

    su = sorted(user_ids)[:sample_print_users]

    # Interest binary matrix → TruncatedSVD (like feature_engine.compute_interest_embeddings)
    all_interests = sorted({i for s in user_interests.values() for i in s})
    if not all_interests:
        interest_emb = {u: np.zeros(interest_dim) for u in user_ids}
    else:
        from scipy.sparse import lil_matrix
        from sklearn.decomposition import TruncatedSVD

        idx = {i: k for k, i in enumerate(all_interests)}
        u_index = {u: k for k, u in enumerate(sorted(user_ids))}
        mat = lil_matrix((len(u_index), len(all_interests)))
        for u, ints in user_interests.items():
            if u not in u_index:
                continue
            for iid in ints:
                if iid in idx:
                    mat[u_index[u], idx[iid]] = 1.0
        mat = mat.tocsr()
        n_comp = min(interest_dim, mat.shape[1] - 1, mat.shape[0] - 1)
        if n_comp < 2:
            interest_emb = {u: np.zeros(max(1, n_comp)) for u in user_ids}
            print("\n  Interest TruncatedSVD: too few columns - skipped.")
        else:
            t1 = time.perf_counter()
            svd = TruncatedSVD(n_components=n_comp, random_state=42)
            Z = svd.fit_transform(mat)
            Z = normalize_rows(Z)
            print(
                f"\n  Interest TruncatedSVD: n_components={n_comp}, "
                f"explained variance ratio sum={svd.explained_variance_ratio_.sum():.4f} "
                f"time={time.perf_counter() - t1:.3f}s"
            )
            interest_emb = {u: Z[row_idx] for u, row_idx in u_index.items()}
            if quiet:
                print("  Sample interest embeddings:")
                for u in su:
                    print_vec(f"    user {u} interest_embedding", interest_emb[u], head=min(8, n_comp))
            else:
                for u in sorted(user_ids):
                    print_vec(f"    user {u} interest_embedding", interest_emb[u], head=min(8, n_comp))

    return post_emb, user_emb, interest_emb


# ── 3) Feed recommender (TruncatedSVD on interactions) ─────────────────────
def run_feed_sim(
    user_ids: List[int],
    post_ids: List[int],
    interactions: List[SimInteraction],
    posts: List[SimPost],
    user_semantic: Dict[int, np.ndarray],
    post_semantic: Dict[int, np.ndarray],
    graph_features: Dict[int, dict],
    top_k: int = 4,
    *,
    quiet: bool = False,
    svd_components: int = 50,
    sample_print_users: int = 6,
    progress_users: int = 500,
) -> Dict[int, List[Tuple[int, float, str]]]:
    print("\n" + "=" * 70)
    print("STEP 3 - FEED RECOMMENDER (interaction SVD + recency + feature re-rank)")
    print("=" * 70)

    from scipy.sparse import csr_matrix
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import normalize

    # aggregate weights
    agg: Dict[Tuple[int, int], float] = defaultdict(float)
    for it in interactions:
        agg[(it.user_id, it.post_id)] += it.weight
    rows, cols, data = [], [], []
    u_idx = {u: i for i, u in enumerate(user_ids)}
    p_idx = {p: j for j, p in enumerate(post_ids)}
    for (u, p), w in agg.items():
        if u in u_idx and p in p_idx:
            rows.append(u_idx[u])
            cols.append(p_idx[p])
            data.append(w)
    shape = (len(user_ids), len(post_ids))
    matrix = csr_matrix((data, (rows, cols)), shape=shape)
    print(f"  Interaction matrix shape: {shape}, nnz={matrix.nnz} density={matrix.nnz / max(shape[0]*shape[1],1):.6f}")
    if quiet:
        coo = matrix.tocoo()
        samp = min(8, matrix.nnz)
        print(f"  Sample nnz (up to {samp}):")
        if samp > 0:
            pick = np.random.default_rng(42).choice(matrix.nnz, size=samp, replace=False)
            for t in pick:
                r, c, v = int(coo.row[t]), int(coo.col[t]), float(coo.data[t])
                print(f"    user {user_ids[r]} -> post {post_ids[c]}: {v}")
    else:
        print("  Non-zero cells (user_idx, post_idx, weight):")
        coo = matrix.tocoo()
        for r, c, v in zip(coo.row, coo.col, coo.data):
            print(f"    user {user_ids[r]} -> post {post_ids[c]}: {v}")

    n_comp = min(svd_components, matrix.shape[0] - 1, matrix.shape[1] - 1)
    if n_comp < 1:
        print("  Matrix too small for SVD - using uniform factors.")
        Uf = normalize(np.ones((len(user_ids), 1)))
        Pf = normalize(np.ones((len(post_ids), 1)))
    else:
        t0 = time.perf_counter()
        svd = TruncatedSVD(n_components=n_comp, random_state=42, n_iter=15)
        Uf = normalize(svd.fit_transform(matrix))
        Pf = normalize(svd.components_.T)
        print(
            f"\n  TruncatedSVD: n_components={n_comp}, explained variance={svd.explained_variance_ratio_.sum():.4f} "
            f"time={time.perf_counter() - t0:.3f}s"
        )
        su = user_ids[:sample_print_users]
        if quiet:
            print(f"  Sample latent factors (first {len(su)} users, first {min(6, n_comp)} dims of U):")
            ui = [u_idx[u] for u in su]
            print(np.array2string(Uf[ui, : min(6, n_comp)], precision=4, floatmode="fixed"))
            print(f"  Post factors P: shape {Pf.shape} (showing row 0 head):")
            print_vec("    post_factor[0]", Pf[0], head=min(8, n_comp))
        else:
            for i, u in enumerate(user_ids):
                print_vec(f"    user_factor user {u}", Uf[i], head=n_comp)
            for j, p in enumerate(post_ids):
                print_vec(f"    post_factor post {p}", Pf[j], head=n_comp)

    post_meta = {p.id: p for p in posts}
    recency = np.array(
        [np.exp(-post_meta[pid].age_days / 30.0) for pid in post_ids],
        dtype=float,
    )
    RECENCY_WEIGHT = 0.3
    FEATURE_WEIGHT = 0.2

    feed_scores: Dict[int, List[Tuple[int, float, str]]] = {}
    n_users = len(user_ids)

    print("\n  Per-user scoring (dot product over all posts; may take a while for huge P)...")
    t1 = time.perf_counter()
    for i, u in enumerate(user_ids):
        raw = Pf @ Uf[i]
        blended = (1 - RECENCY_WEIGHT) * raw + RECENCY_WEIGHT * recency
        k = min(top_k, len(blended))
        top_idx = np.argpartition(blended, -k)[-k:]
        top_idx = top_idx[np.argsort(blended[top_idx])[::-1]]

        stage2: List[Tuple[int, float, float, str]] = []
        uvec = user_semantic.get(u)
        upr = graph_features[u]["pagerank"]
        for j in top_idx:
            pid = post_ids[j]
            base = float(blended[j])
            pvec = post_semantic.get(pid)
            topic_bonus = 0.0
            if uvec is not None and pvec is not None:
                nu = np.linalg.norm(uvec) * np.linalg.norm(pvec)
                if nu > 0:
                    topic_bonus = float(np.dot(uvec, pvec) / nu)
            feature_boost = 0.6 * topic_bonus + 0.4 * upr
            final = (1 - FEATURE_WEIGHT) * base + FEATURE_WEIGHT * feature_boost
            explain = f"base={base:.4f} topic_cos={topic_bonus:.4f} pr={upr:.4f} -> final={final:.4f}"
            stage2.append((pid, final, base, explain))

        stage2.sort(key=lambda x: -x[1])
        feed_scores[u] = [(pid, sc, ex) for pid, sc, _, ex in stage2]

        if quiet:
            if (i + 1) % progress_users == 0 or i + 1 == n_users:
                print(f"    scored users {i + 1}/{n_users} ...")
        else:
            print(f"\n    --- User {u} ---")
            for rank, (pid, sc, ex) in enumerate(feed_scores[u], 1):
                print(f"      #{rank} post {pid}  score={sc:.4f}  ({ex})")

    if quiet:
        print(f"  Feed scoring wall time: {time.perf_counter() - t1:.3f}s")
        su = sorted(user_ids)[:sample_print_users]
        print(f"  Sample feed outputs (users {su}):")
        for u in su:
            print(f"    user {u}:")
            for rank, (pid, sc, ex) in enumerate(feed_scores[u], 1):
                print(f"      #{rank} post {pid}  score={sc:.4f}  ({ex})")

    return feed_scores


# ── 4) People recommender ───────────────────────────────────────────────────
def _score_people_pair(
    u: int,
    t: int,
    my_i: Set[int],
    my_c: int,
    my_fof: Set[int],
    my_t: np.ndarray,
    graph_features: Dict[int, dict],
    user_interests: Dict[int, Set[int]],
    user_semantic: Dict[int, np.ndarray],
    W_FOF: float,
    W_PR: float,
    W_COM: float,
    W_INT: float,
    W_TOP: float,
    min_score: float,
) -> Tuple[float, dict] | None:
    if t == u:
        return None
    tg = graph_features[t]
    fof_s = 1.0 if t in my_fof else 0.0
    pr_s = tg["pagerank"]
    com_s = 1.0 if my_c >= 0 and my_c == tg["community_id"] else 0.0
    mi, ti = my_i, user_interests.get(t, set())
    int_s = (len(mi & ti) / len(mi | ti)) if mi and ti else 0.0
    ut, vt = my_t, user_semantic[t]
    nrm = np.linalg.norm(ut) * np.linalg.norm(vt)
    top_s = float(np.dot(ut, vt) / nrm) if nrm > 0 else 0.0
    total = (
        W_FOF * fof_s
        + W_PR * pr_s
        + W_COM * com_s
        + W_INT * int_s
        + W_TOP * top_s
    )
    if total < min_score:
        return None
    breakdown = {
        "fof": round(fof_s, 3),
        "pagerank": round(pr_s, 3),
        "community": round(com_s, 3),
        "interest_jaccard": round(int_s, 3),
        "topic_cos": round(top_s, 3),
    }
    return total, breakdown


def run_people_sim(
    user_ids: List[int],
    user_interests: Dict[int, Set[int]],
    graph_features: Dict[int, dict],
    user_semantic: Dict[int, np.ndarray],
    top_k: int = 4,
    *,
    quiet: bool = False,
    rng: np.random.Generator | None = None,
    candidate_pool: int = 400,
    sample_print_users: int = 6,
    progress_users: int = 500,
    min_score: float = 0.05,
) -> Dict[int, List[Tuple[int, float, dict]]]:
    print("\n" + "=" * 70)
    print("STEP 4 - PEOPLE RECOMMENDER (FoF + PageRank + community + Jaccard + topic)")
    print("=" * 70)

    W_FOF, W_PR, W_COM, W_INT, W_TOP = 0.25, 0.10, 0.15, 0.30, 0.20
    rng = rng or np.random.default_rng(0)
    U = len(user_ids)
    use_candidates = quiet or U > 80

    comm_buckets: Dict[int, List[int]] = defaultdict(list)
    for uid in user_ids:
        comm_buckets[graph_features[uid]["community_id"]].append(uid)

    uid_set = set(user_ids)
    out: Dict[int, List[Tuple[int, float, dict]]] = {}
    t0 = time.perf_counter()

    for ui, u in enumerate(user_ids):
        my_i = user_interests.get(u, set())
        my_c = graph_features[u]["community_id"]
        my_fof = graph_features[u]["fof_set"]
        my_t = user_semantic[u]
        cands: List[Tuple[int, float, dict]] = []

        if use_candidates:
            pool: Set[int] = set(my_fof)
            same = comm_buckets.get(my_c, [])
            if my_c >= 0 and same:
                cap = min(250, len(same))
                for v in same[:cap]:
                    if v != u:
                        pool.add(v)
            for v in user_ids:
                if v != u and my_i & user_interests.get(v, set()):
                    pool.add(v)
                if len(pool) >= candidate_pool:
                    break
            others = [v for v in user_ids if v != u and v not in pool]
            need = max(0, candidate_pool - len(pool))
            if others and need > 0:
                pick = rng.choice(len(others), size=min(need, len(others)), replace=False)
                for i in pick:
                    pool.add(others[int(i)])
            targets = list(pool)
        else:
            targets = [t for t in user_ids if t != u]

        for t in targets:
            res = _score_people_pair(
                u, t, my_i, my_c, my_fof, my_t,
                graph_features, user_interests, user_semantic,
                W_FOF, W_PR, W_COM, W_INT, W_TOP, min_score,
            )
            if res is None:
                continue
            sc, bd = res
            cands.append((t, sc, bd))

        cands.sort(key=lambda x: -x[1])
        out[u] = cands[:top_k]

        if quiet:
            if (ui + 1) % progress_users == 0 or ui + 1 == U:
                print(f"    people scored {ui + 1}/{U} ...")
        else:
            print(f"\n  User {u} top {top_k} stranger candidates:")
            for tid, sc, bd in out[u]:
                print(f"    target {tid}  score={sc:.4f}  breakdown={bd}")

    print(f"  People recommender wall time: {time.perf_counter() - t0:.3f}s")
    if use_candidates:
        print(f"  Mode: candidate pool ~{candidate_pool} per user (scalable)")
    else:
        print("  Mode: full pairwise scan (toy scale only)")

    if quiet:
        su = sorted(user_ids)[:sample_print_users]
        print(f"  Sample people recommendations (users {su}):")
        for u in su:
            print(f"    user {u}:")
            for tid, sc, bd in out[u]:
                print(f"      target {tid}  score={sc:.4f}  {bd}")

    return out


# ── 5) Zone recommender (multi-zone) ───────────────────────────────────────
def run_zone_sim(
    user_ids: List[int],
    user_interests: Dict[int, Set[int]],
    user_semantic: Dict[int, np.ndarray],
    zone_members: Dict[int, Set[int]],
    zone_posts: Dict[int, List[int]],
    post_semantic: Dict[int, np.ndarray],
    graph_features: Dict[int, dict],
    *,
    quiet: bool = False,
    sample_zones: int = 2,
    sample_users: int = 6,
) -> None:
    print("\n" + "=" * 70)
    print("STEP 5 - ZONE RECOMMENDER (interest + semantic + community + activity)")
    print("=" * 70)

    if not zone_members:
        print("  No zones in dataset.")
        return

    max_act = max((len(zone_posts.get(z, [])) for z in zone_members), default=1)
    zero = np.zeros_like(next(iter(user_semantic.values())))
    zone_scores_all: List[float] = []

    zids = sorted(zone_members.keys())
    big = len(user_ids) > 120
    if quiet or big:
        show_zones = zids[:sample_zones]
    else:
        show_zones = zids
    # Avoid huge stdout: sample users when many users
    su = sorted(user_ids)[:sample_users] if (quiet or big) else user_ids
    if big and not quiet:
        print(f"  (Large graph: showing first {len(show_zones)} zones x {len(su)} sample users)")

    for zid in show_zones:
        members = zone_members.get(zid, set())
        z_interests: Set[int] = set()
        for m in members:
            z_interests |= user_interests.get(m, set())
        vecs = [user_semantic[m] for m in members if m in user_semantic]
        zone_centroid = np.mean(vecs, axis=0) if vecs else zero.copy()
        if quiet or zid == show_zones[0]:
            print_vec(f"  Zone {zid} semantic centroid", zone_centroid, head=10)
        if not quiet and not big:
            print(f"  Zone {zid}: |members|={len(members)} |posts|={len(zone_posts.get(zid, []))}")
        elif not quiet and big and zid == show_zones[0]:
            print(f"  Zone {zid}: |members|={len(members)} |posts|={len(zone_posts.get(zid, []))} ...")

        for u in su:
            if u in members:
                continue
            my_i = user_interests.get(u, set())
            j = len(my_i & z_interests) / len(my_i | z_interests) if (my_i or z_interests) else 0.0
            nu = np.linalg.norm(user_semantic[u]) * np.linalg.norm(zone_centroid)
            sem = float(np.dot(user_semantic[u], zone_centroid) / nu) if nu > 0 else 0.0
            z_mem = zone_members.get(zid, set())
            community_score = 0.0
            if z_mem:
                same_c = sum(
                    1 for mid in z_mem
                    if graph_features.get(mid, {}).get("community_id")
                    == graph_features[u]["community_id"]
                    and graph_features[u]["community_id"] >= 0
                )
                community_score = same_c / len(z_mem)
            act = len(zone_posts.get(zid, [])) / max(max_act, 1)
            total = 0.20 * j + 0.25 * sem + 0.15 * community_score + 0.40 * act
            zone_scores_all.append(total)
            if not quiet:
                print(
                    f"    user {u} -> zone {zid}: jaccard={j:.4f} cos={sem:.4f} "
                    f"comm_frac={community_score:.4f} act={act:.4f} score={total:.4f}"
                )

    if quiet and zone_scores_all:
        arr = np.array(zone_scores_all)
        print(
            f"  Zone scores (sampled zone/user pairs): count={len(arr)} "
            f"min={arr.min():.4f} max={arr.max():.4f} mean={arr.mean():.4f}"
        )


# ── 6) Safety ─────────────────────────────────────────────────────────────
def run_safety_sim(posts: List[SimPost], *, quiet: bool = False, sample_lines: int = 12) -> None:
    print("\n" + "=" * 70)
    print("STEP 6 - SAFETY (regex toxicity / spam - same family as ml/safety.py)")
    print("=" * 70)
    scores = []
    n_flag = 0
    for p in posts:
        s = score_toxicity(p.content)
        scores.append(s)
        if s >= 0.3:
            n_flag += 1
    arr = np.array(scores)
    print(
        f"  Scanned {len(posts)} posts: flagged (>={0.3})={n_flag} "
        f"({100 * n_flag / max(len(posts), 1):.2f}%) "
        f"toxicity min={arr.min():.4f} max={arr.max():.4f} mean={arr.mean():.4f}"
    )
    if quiet:
        # show a few highest toxicity
        order = np.argsort(-arr)[:sample_lines]
        print(f"  Top-{sample_lines} toxicity posts:")
        for i in order:
            p = posts[int(i)]
            s = scores[int(i)]
            flag = "FLAG" if s >= 0.3 else "ok"
            print(f"    post {p.id}: {s:.4f} [{flag}] {p.content[:70]}...")
    else:
        for p, s in zip(posts, scores):
            flag = "FLAG" if s >= 0.3 else "ok"
            print(f"  Post {p.id}: toxicity={s:.4f} [{flag}]  text={p.content[:60]}...")


# ── 7) Evaluation ───────────────────────────────────────────────────────────
def run_eval_sim(
    feed_scores: Dict[int, List[Tuple[int, float, str]]],
    interactions: List[SimInteraction],
    posts: List[SimPost],
    k: int = 3,
    *,
    quiet: bool = False,
) -> None:
    print("\n" + "=" * 70)
    print("STEP 7 - EVALUATION (Precision@K, coverage, category diversity)")
    print("=" * 70)

    ground_truth: Dict[int, Set[int]] = defaultdict(set)
    for it in interactions:
        if it.action in ("like", "comment"):
            ground_truth[it.user_id].add(it.post_id)

    user_recs: Dict[int, List[int]] = {u: [pid for pid, _, _ in recs] for u, recs in feed_scores.items()}

    precs = []
    for uid, recs in user_recs.items():
        truth = ground_truth.get(uid, set())
        if not truth:
            continue
        top_kk = recs[:k]
        hits = sum(1 for pid in top_kk if pid in truth)
        precs.append(hits / k)
    p_at_k = sum(precs) / len(precs) if precs else 0.0
    print(f"  Precision@{k} (vs posts user liked/commented): {p_at_k:.4f}  (users with any engagement: {len(precs)})")

    all_posts = {p.id for p in posts}
    rec_set = {pid for recs in user_recs.values() for pid in recs}
    coverage = len(rec_set) / max(len(all_posts), 1)
    print(f"  Catalog coverage: {coverage:.4f}  ({len(rec_set)}/{len(all_posts)} distinct posts in some feed)")

    post_cat = {p.id: p.category for p in posts}
    divs = []
    for uid, recs in user_recs.items():
        cats = {post_cat[pid] for pid in recs if pid in post_cat}
        divs.append(len(cats))
    avg_div = sum(divs) / max(len(divs), 1)
    print(f"  Avg distinct categories per user feed (all recommended): {avg_div:.2f}")

    hit_users = sum(1 for uid, recs in user_recs.items() if recs[:k] and ground_truth.get(uid) & set(recs[:k]))
    print(f"  Users with >=1 hit in top-{k}: {hit_users} / {len(user_recs)}")

    if quiet:
        print("  Ground truth: omitted (large); sample user ids with likes/comments:")
        samp = sorted(ground_truth.keys())[:15]
        for uid in samp:
            s = sorted(ground_truth[uid])
            head = s[:8]
            tail = "..." if len(s) > 8 else ""
            print(f"    user {uid}: {head}{tail} (|truth|={len(s)})")
    else:
        print("\n  Ground truth (like + comment post sets):")
        for uid in sorted(ground_truth.keys()):
            print(f"    user {uid}: {sorted(ground_truth[uid])}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate Strange Street ML pipeline in memory (toy or large synthetic data)."
    )
    parser.add_argument(
        "--large",
        action="store_true",
        help="Use a large preset (many users/posts/interactions). Implies summarized output.",
    )
    parser.add_argument("--users", type=int, default=None, help="Number of users (custom big run).")
    parser.add_argument("--posts", type=int, default=None, help="Number of posts.")
    parser.add_argument("--follows", type=int, default=None, help="Target number of follow edges.")
    parser.add_argument("--interactions", type=int, default=None, help="Number of interaction events.")
    parser.add_argument(
        "--num-interest-labels",
        type=int,
        default=None,
        metavar="I",
        help="Number of distinct interest ids in [0..I-1) for large synthetic users.",
    )
    parser.add_argument("--zones", type=int, default=None, help="Number of zones.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full detail even for large runs (very long output).",
    )
    parser.add_argument(
        "--real-embeddings",
        action="store_true",
        help="Use all-MiniLM-L6-v2 for post embeddings (disabled if posts > 2000).",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed.")
    parser.add_argument("--feed-top-k", type=int, default=None, help="Top posts per user in feed output.")
    parser.add_argument("--people-top-k", type=int, default=None, help="Top people recommendations per user.")
    parser.add_argument("--svd-components", type=int, default=None, help="TruncatedSVD components for feed.")
    parser.add_argument("--embedding-dim", type=int, default=None, help="Synthetic embedding dimension.")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    use_big = args.large or any(
        x is not None for x in (args.users, args.posts, args.follows, args.interactions)
    )
    quiet = use_big and not args.verbose

    if use_big:
        cfg = BigSimConfig()
        if args.users is not None:
            cfg.users = args.users
        if args.posts is not None:
            cfg.posts = args.posts
        if args.follows is not None:
            cfg.num_follows = args.follows
        if args.interactions is not None:
            cfg.num_interactions = args.interactions
        if args.num_interest_labels is not None:
            cfg.num_interests = args.num_interest_labels
        if args.zones is not None:
            cfg.zones = args.zones
        if args.large and not any(
            x is not None for x in (args.users, args.posts, args.follows, args.interactions)
        ):
            # default "large" preset
            cfg = BigSimConfig(
                users=5000,
                posts=15000,
                num_follows=90000,
                num_interactions=450000,
                num_interests=45,
                zones=30,
            )

        t_gen = time.perf_counter()
        users, posts, follows, interactions, zm, zone_posts_map = build_large_synthetic_world(cfg, rng)
        print(f"\n  [data gen] users={len(users)} posts={len(posts)} follows={len(follows)} "
              f"interactions={len(interactions)} zones={len(set(z for z,_ in zm))} "
              f"time={time.perf_counter() - t_gen:.2f}s")
    else:
        users, posts, follows, interactions, zm, zone_posts_map = build_synthetic_world(rng)

    user_ids = [u.id for u in users]
    post_ids = [p.id for p in posts]
    user_interests = {u.id: set(u.interests) for u in users}

    zone_members: Dict[int, Set[int]] = defaultdict(set)
    for zid, uid in zm:
        zone_members[zid].add(uid)

    print("+" + "-" * 68 + "+")
    print("|" + " Strange Street - ML PIPELINE SIMULATION (in-memory) ".center(68) + "|")
    print("+" + "-" * 68 + "+")
    if not quiet:
        print("\nSynthetic dataset:")
        print(f"  Users: {user_ids}")
        print(f"  Posts: {post_ids}")
        print(f"  Follows: {follows}")
        print(
            "  Interactions:",
            [(it.user_id, it.post_id, it.action, it.weight) for it in interactions],
            f"count={len(interactions)}",
        )
    else:
        print("\nDataset summary:")
        print(f"  users={len(user_ids)} posts={len(post_ids)} follows={len(follows)} "
              f"interactions={len(interactions)} unique_zones={len(zone_members)}")

    n_u, n_p = len(user_ids), len(post_ids)
    if n_u * n_p > 80_000_000:
        print(
            f"\n  WARNING: n_users * n_posts = {n_u * n_p:,} (feed scoring loops over all posts per user).\n"
            "  Consider reducing --posts or --users for faster runs.\n"
        )

    graph_features = run_graph_sim(
        user_ids,
        follows,
        user_interests,
        rng,
        quiet=quiet,
        max_fof=80 if use_big else 50,
        sample_print_users=8,
    )

    if use_big:
        interest_dim = min(50, max(2, cfg.num_interests - 1), max(2, n_u - 1))
    else:
        interest_dim = min(4, max(2, n_u - 1))

    emb_dim = args.embedding_dim if args.embedding_dim is not None else (48 if use_big else 16)

    post_sem, user_sem, _interest_emb = run_feature_sim(
        posts,
        user_ids,
        user_interests,
        interest_dim=interest_dim,
        rng=rng,
        real_embeddings=args.real_embeddings,
        quiet=quiet,
        embedding_dim=emb_dim,
        sample_print_posts=5 if quiet else len(posts),
        sample_print_users=8,
    )

    svd_c = args.svd_components if args.svd_components is not None else (min(40, n_u - 1, n_p - 1) if use_big else min(4, n_u - 1, n_p - 1))
    svd_c = max(1, svd_c)

    fk = args.feed_top_k if args.feed_top_k is not None else (20 if use_big else 4)
    pk = args.people_top_k if args.people_top_k is not None else (15 if use_big else 4)

    feed_scores = run_feed_sim(
        user_ids,
        post_ids,
        interactions,
        posts,
        user_sem,
        post_sem,
        graph_features,
        top_k=fk,
        quiet=quiet,
        svd_components=svd_c,
        sample_print_users=6,
        progress_users=500,
    )

    run_people_sim(
        user_ids,
        user_interests,
        graph_features,
        user_sem,
        top_k=pk,
        quiet=quiet,
        rng=rng,
        candidate_pool=500 if use_big else 400,
        sample_print_users=6,
        progress_users=500,
    )

    run_zone_sim(
        user_ids,
        user_interests,
        user_sem,
        zone_members,
        zone_posts_map,
        post_sem,
        graph_features,
        quiet=quiet,
        sample_zones=3,
        sample_users=6,
    )

    run_safety_sim(posts, quiet=quiet, sample_lines=15)

    run_eval_sim(feed_scores, interactions, posts, k=min(10, fk) if use_big else 3, quiet=quiet)

    print("\n" + "=" * 70)
    print("DONE - This script is educational; production uses Postgres + full pipeline.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
