"""
Strange Street — ML Pipeline Orchestrator
===========================================
Single entry point to run the entire ML intelligence pipeline.
Executes all steps in the correct dependency order.

Usage:
    python ml/run_pipeline.py           # run all steps
    python ml/run_pipeline.py --skip-safety   # skip safety checks

Steps:
    1. Feature Engine  → text/interest/behavioral features
    2. Graph Engine    → PageRank, Louvain, FoF, label propagation
    3. Feed Recommender → SVD + feature re-ranking → FeedScore
    4. People Recommender → stranger scores → PeopleScore
    5. Zone Recommender → zone scores → ZoneScore
    6. Safety Module   → toxicity flags + author cap
    7. Evaluation      → metrics report
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
from database import SessionLocal, engine, Base

# Import all models so SQLAlchemy registers them before create_all
import app.models  # noqa — registers all tables including new ML ones

# Ensure all tables exist (including new ML tables)
Base.metadata.create_all(bind=engine)


from datetime import datetime, timezone

def run_pipeline(skip_safety: bool = False, run_id: int = None):
    """Execute the full ML pipeline."""
    print("╔══════════════════════════════════════╗")
    print("║  Strange Street ML Intelligence      ║")
    print("║  Full Pipeline Run                   ║")
    print("╚══════════════════════════════════════╝\n")

    start = time.time()
    db = SessionLocal()

    def update_progress(step: int, status: str = "running", error: str = None):
        if run_id:
            from app.models import PipelineRun
            run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
            if run:
                run.steps_completed = step
                run.status = status
                if error:
                    run.error_msg = error[:500]
                if status in ["success", "failed"]:
                    run.completed_at = datetime.now(timezone.utc)
                    run.duration_sec = time.time() - start
                db.commit()

    try:
        # ── Step 1: Graph Engine ──────────────────────────────────────
        print("━━━ [1/7] Graph Engine ━━━")
        from ml.graph_engine import run as run_graph
        graph_features = run_graph(db)
        update_progress(1)
        print()

        # ── Step 2: Feature Engine ────────────────────────────────────
        print("━━━ [2/7] Feature Engine ━━━")
        from ml.feature_engine import run as run_features
        feature_data = run_features(db, graph_features=graph_features)
        update_progress(2)
        print()

        # ── Step 3: Feed Recommender ──────────────────────────────────
        print("━━━ [3/7] Feed Recommender (SVD) ━━━")
        from ml.train_recommender import run as run_feed
        run_feed()  # uses its own DB session
        update_progress(3)
        print()

        # ── Step 4: People Recommender ────────────────────────────────
        print("━━━ [4/7] People Recommender ━━━")
        from ml.people_recommender import run as run_people
        run_people(db, graph_features=graph_features)
        update_progress(4)
        print()

        # ── Step 5: Zone Recommender ──────────────────────────────────
        print("━━━ [5/7] Zone Recommender ━━━")
        from ml.zone_recommender import run as run_zones
        run_zones(db, graph_features=graph_features)
        update_progress(5)
        print()

        # ── Step 6: Safety ────────────────────────────────────────────
        if not skip_safety:
            print("━━━ [6/7] Safety Module ━━━")
            from ml.safety import run as run_safety
            run_safety(db)
            print()
        else:
            print("━━━ [6/7] Safety Module — SKIPPED ━━━\n")
        update_progress(6)

        # ── Step 7: Evaluation ────────────────────────────────────────
        print("━━━ [7/7] Evaluation ━━━")
        from ml.evaluate import run as run_eval
        run_eval(db)
        update_progress(7, status="success")
        print()

    except Exception as e:
        print(f"\n✗ Pipeline failed at: {e}")
        update_progress(run.steps_completed if 'run' in locals() else 0, status="failed", error=str(e))
        raise
    finally:
        db.close()

    elapsed = time.time() - start
    print(f"\n{'═' * 42}")
    print(f"  Pipeline complete in {elapsed:.1f}s")
    print(f"{'═' * 42}")


if __name__ == "__main__":
    skip = "--skip-safety" in sys.argv
    run_pipeline(skip_safety=skip)
