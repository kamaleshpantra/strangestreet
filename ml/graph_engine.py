"""
Strange Street — Graph Engine
==============================
Builds social graphs and extracts structural features:
  - PageRank (user influence)
  - Louvain community detection (organic clusters)
  - Friend-of-friend sets (2nd-degree connections)
  - Label propagation (interest inference for sparse profiles)

Usage:
    python ml/graph_engine.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import networkx as nx
from community import community_louvain
from sqlalchemy.orm import Session
from database import SessionLocal
from app.models import User, Interest, Connection, user_interests, followers


class GraphEngine:
    """Builds and analyzes social graphs for ML features."""

    def __init__(self, db: Session):
        self.db = db
        self.follower_graph = None
        self.connection_graph = None
        self.user_features = {}  # uid → {pagerank, community_id, degree, fof_set}

    # ── Build Graphs ──────────────────────────────────────────────────────

    def build_follower_graph(self):
        """Build directed follower graph."""
        print("  [Graph] Building follower graph...")
        G = nx.DiGraph()

        # Add all users as nodes
        user_ids = [uid for (uid,) in self.db.query(User.id).filter(User.is_active == True).all()]
        G.add_nodes_from(user_ids)

        # Add edges
        follow_rows = self.db.execute(followers.select()).fetchall()
        for row in follow_rows:
            G.add_edge(row.follower_id, row.followed_id)

        self.follower_graph = G
        print(f"  [Graph] ✓ Follower graph: {G.number_of_nodes()} nodes, "
              f"{G.number_of_edges()} edges")
        return G

    def build_connection_graph(self):
        """Build undirected connection graph (accepted connections only)."""
        print("  [Graph] Building connection graph...")
        G = nx.Graph()

        user_ids = [uid for (uid,) in self.db.query(User.id).filter(User.is_active == True).all()]
        G.add_nodes_from(user_ids)

        connections = self.db.query(Connection).filter(
            Connection.status == "accepted"
        ).all()
        for c in connections:
            G.add_edge(c.requester_id, c.requested_id)

        self.connection_graph = G
        print(f"  [Graph] ✓ Connection graph: {G.number_of_nodes()} nodes, "
              f"{G.number_of_edges()} edges")
        return G

    # ── PageRank ──────────────────────────────────────────────────────────

    def compute_pagerank(self) -> dict:
        """PageRank on follower graph → user influence scores."""
        if self.follower_graph is None:
            self.build_follower_graph()

        G = self.follower_graph
        if G.number_of_edges() == 0:
            print("  [Graph] No edges for PageRank. Using uniform scores.")
            return {n: 1.0 / max(G.number_of_nodes(), 1) for n in G.nodes()}

        print(f"  [Graph] Computing PageRank...")
        scores = nx.pagerank(G, alpha=0.85, max_iter=100)
        # Normalize to 0-1 range
        max_score = max(scores.values()) if scores else 1
        if max_score > 0:
            scores = {uid: s / max_score for uid, s in scores.items()}

        print(f"  [Graph] ✓ PageRank computed for {len(scores)} users")
        return scores

    # ── Louvain Community Detection ───────────────────────────────────────

    def compute_communities(self) -> dict:
        """Louvain clustering on undirected follower graph → community IDs."""
        if self.follower_graph is None:
            self.build_follower_graph()

        # Louvain needs undirected graph
        G_undirected = self.follower_graph.to_undirected()

        # Remove isolated nodes for better clustering
        isolates = list(nx.isolates(G_undirected))
        G_connected = G_undirected.copy()
        G_connected.remove_nodes_from(isolates)

        if G_connected.number_of_nodes() < 3:
            print("  [Graph] Too few connected nodes for community detection.")
            return {n: 0 for n in self.follower_graph.nodes()}

        print(f"  [Graph] Running Louvain community detection...")
        partition = community_louvain.best_partition(G_connected, random_state=42)

        # Assign isolated nodes to community -1
        for node in isolates:
            partition[node] = -1

        n_communities = len(set(partition.values()) - {-1})
        print(f"  [Graph] ✓ Found {n_communities} communities "
              f"({len(isolates)} isolated users)")
        return partition

    # ── Friend-of-Friend ──────────────────────────────────────────────────

    def compute_fof_sets(self, max_fof: int = 50) -> dict:
        """2nd-degree connections for each user."""
        if self.follower_graph is None:
            self.build_follower_graph()

        print(f"  [Graph] Computing friend-of-friend sets...")
        G = self.follower_graph
        fof_map = {}

        for node in G.nodes():
            # Direct neighbors (people I follow)
            direct = set(G.successors(node))
            # Friends of friends
            fof = set()
            for friend in direct:
                fof.update(G.successors(friend))
            # Remove self and direct connections
            fof.discard(node)
            fof -= direct
            # Limit size
            if len(fof) > max_fof:
                fof = set(list(fof)[:max_fof])
            fof_map[node] = fof

        total_fof = sum(len(v) for v in fof_map.values())
        print(f"  [Graph] ✓ FoF sets for {len(fof_map)} users "
              f"(avg {total_fof / max(len(fof_map), 1):.1f} FoF per user)")
        return fof_map

    # ── Label Propagation (Interest Inference) ────────────────────────────

    def infer_interests(self, min_interests: int = 3) -> dict:
        """
        For users with few interests, infer likely interests from their
        neighbors' interest patterns using the follower graph.
        """
        if self.follower_graph is None:
            self.build_follower_graph()

        print(f"  [Graph] Inferring interests for sparse profiles...")
        G = self.follower_graph

        # Load all user interests
        interest_rows = self.db.execute(user_interests.select()).fetchall()
        user_interest_map = {}
        for row in interest_rows:
            user_interest_map.setdefault(row.user_id, set()).add(row.interest_id)

        # Find sparse users
        sparse_users = [
            uid for uid in G.nodes()
            if len(user_interest_map.get(uid, set())) < min_interests
        ]

        if not sparse_users:
            print("  [Graph] No sparse profiles found. Skipping inference.")
            return {}

        inferred = {}
        for uid in sparse_users:
            # Collect neighbors' interests with frequency counts
            neighbor_interests = {}
            for neighbor in G.predecessors(uid):  # people who follow me
                for iid in user_interest_map.get(neighbor, set()):
                    neighbor_interests[iid] = neighbor_interests.get(iid, 0) + 1

            # Also check who I follow
            for neighbor in G.successors(uid):
                for iid in user_interest_map.get(neighbor, set()):
                    neighbor_interests[iid] = neighbor_interests.get(iid, 0) + 1

            # Remove interests user already has
            existing = user_interest_map.get(uid, set())
            candidates = {
                iid: count for iid, count in neighbor_interests.items()
                if iid not in existing
            }

            # Top-5 most common among neighbors
            if candidates:
                top = sorted(candidates.items(), key=lambda x: -x[1])[:5]
                inferred[uid] = [iid for iid, _ in top]

        print(f"  [Graph] ✓ Inferred interests for {len(inferred)} sparse users")
        return inferred

    # ── Aggregate ─────────────────────────────────────────────────────────

    def compute_all(self) -> dict:
        """Run all graph computations and return per-user feature dicts."""
        self.build_follower_graph()
        self.build_connection_graph()

        pagerank = self.compute_pagerank()
        communities = self.compute_communities()
        fof_sets = self.compute_fof_sets()
        inferred = self.infer_interests()

        # Aggregate per user
        result = {}
        for uid in self.follower_graph.nodes():
            result[uid] = {
                "pagerank": round(pagerank.get(uid, 0.0), 6),
                "community_id": communities.get(uid, -1),
                "degree": self.follower_graph.degree(uid),
                "fof_count": len(fof_sets.get(uid, set())),
                "fof_set": list(fof_sets.get(uid, set())),
                "inferred_interests": inferred.get(uid, []),
            }

        print(f"\n  [Graph] ✓ All graph features computed for {len(result)} users")
        return result


def run(db: Session = None):
    """Run the graph engine and return features."""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        engine = GraphEngine(db)
        return engine.compute_all()
    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    print("═══ Strange Street Graph Engine ═══\n")
    features = run()
    print(f"\n✓ Graph engine complete. {len(features)} users processed.")
