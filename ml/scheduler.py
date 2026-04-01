"""
ML Pipeline Scheduler
=====================
Runs the ML pipeline on a configurable schedule.
Uses APScheduler for job scheduling.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_scheduled_pipeline(skip_safety: bool = False):
    """Execute ML pipeline triggered by scheduler using the consolidated orchestrator."""
    from database import SessionLocal
    from app.models import PipelineRun
    from ml.run_pipeline import run_pipeline as ml_run

    db = SessionLocal()
    try:
        # Create the run record first to get an ID
        run = PipelineRun(
            status="pending",
            triggered_by="scheduler",
            total_steps=7,
        )
        db.add(run)
        db.commit()
        run_id = run.id
        db.close() # ml_run will handle its own session

        logger.info(f"[ML Scheduler] Starting pipeline run #{run_id}")
        ml_run(skip_safety=skip_safety, run_id=run_id)

    except Exception as e:
        logger.error(f"[ML Scheduler] Error: {e}")


def start_scheduler():
    """Initialize and start the scheduler."""
    if scheduler.running:
        logger.info("[ML Scheduler] Already running")
        return

    trigger = CronTrigger(hour=2, minute=0)
    scheduler.add_job(
        run_scheduled_pipeline,
        trigger=trigger,
        args=[False],
        id="ml_pipeline_daily",
        name="Daily ML Pipeline (2:00 AM)",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[ML Scheduler] Started - Daily pipeline scheduled for 2:00 AM")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[ML Scheduler] Stopped")


def run_pipeline_now(skip_safety: bool = False):
    """Manually trigger a pipeline run immediately."""
    import threading
    t = threading.Thread(target=run_scheduled_pipeline, args=(skip_safety,))
    t.daemon = True
    t.start()
    logger.info("[ML Scheduler] Manual pipeline triggered")


if __name__ == "__main__":
    print("Starting ML Pipeline Scheduler...")
    start_scheduler()
    print("Scheduler running. Press Ctrl+C to stop.")

    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        stop_scheduler()
