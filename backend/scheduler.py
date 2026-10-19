"""
APScheduler-based background sync job manager.
Reads intervals from the settings table and schedules product/inventory/pricing syncs
for all active suppliers.
"""
import asyncio
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None
_pool = None

JOB_IDS = {
    "products": "auto_sync_products",
    "inventory": "auto_sync_inventory",
    "pricing": "auto_sync_pricing",
}


async def _run_sync_for_all_suppliers(sync_type: str):
    """Run a specific sync type for every active supplier."""
    if _pool is None:
        logger.warning("Scheduler: DB pool not available, skipping %s sync", sync_type)
        return

    try:
        async with _pool.acquire() as conn:
            suppliers = await conn.fetch("SELECT id, supplier_name FROM suppliers WHERE is_active = TRUE")

        if not suppliers:
            logger.info("Scheduler: No active suppliers for %s sync", sync_type)
            return

        # Import sync tasks lazily to avoid circular imports
        from routes.sync import (
            sync_products_task,
            sync_inventory_task,
            sync_pricing_task,
        )
        from deps import create_sync_log as _create_sync_log

        task_map = {
            "products": sync_products_task,
            "inventory": sync_inventory_task,
            "pricing": sync_pricing_task,
        }
        task_fn = task_map.get(sync_type)
        if not task_fn:
            return

        for supplier in suppliers:
            sid = supplier["id"]
            sname = supplier["supplier_name"]
            log_id = await _create_sync_log(sid, sname, sync_type, f"[Auto] Starting scheduled {sync_type} sync...")
            logger.info("Scheduler: Triggering %s sync for %s", sync_type, sname)
            asyncio.create_task(task_fn(sid, log_id))

    except Exception as e:
        logger.error("Scheduler: Error running %s sync: %s", sync_type, e)


async def _sync_products_job():
    await _run_sync_for_all_suppliers("products")

async def _sync_inventory_job():
    await _run_sync_for_all_suppliers("inventory")

async def _sync_pricing_job():
    await _run_sync_for_all_suppliers("pricing")


def init_scheduler(pool):
    """Create the scheduler instance and store the DB pool reference."""
    global scheduler, _pool
    _pool = pool
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()
    logger.info("Scheduler: Started (no jobs scheduled until settings loaded)")


async def apply_schedule_from_settings():
    """Read settings and add/update/remove jobs accordingly."""
    global scheduler
    if scheduler is None or _pool is None:
        return

    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
    except Exception as e:
        logger.error("Scheduler: Cannot read settings: %s", e)
        return

    if not row:
        return

    enabled = row.get("auto_sync_enabled", False)

    if not enabled:
        # Remove all scheduled jobs
        for job_id in JOB_IDS.values():
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                logger.info("Scheduler: Removed job %s (auto-sync disabled)", job_id)
        return

    # Schedule / reschedule jobs
    product_hours = int(row.get("sync_products_interval_hours") or 24)
    inventory_minutes = int(row.get("sync_inventory_interval_minutes") or 30)
    pricing_hours = int(row.get("sync_pricing_interval_hours") or 12)

    job_configs = [
        (JOB_IDS["products"], _sync_products_job, {"hours": product_hours}),
        (JOB_IDS["inventory"], _sync_inventory_job, {"minutes": inventory_minutes}),
        (JOB_IDS["pricing"], _sync_pricing_job, {"hours": pricing_hours}),
    ]

    for job_id, func, interval_kwargs in job_configs:
        existing = scheduler.get_job(job_id)
        trigger = IntervalTrigger(**interval_kwargs)
        if existing:
            scheduler.reschedule_job(job_id, trigger=trigger)
            logger.info("Scheduler: Rescheduled %s with %s", job_id, interval_kwargs)
        else:
            scheduler.add_job(func, trigger=trigger, id=job_id, replace_existing=True)
            logger.info("Scheduler: Added %s with %s", job_id, interval_kwargs)


def get_scheduler_status() -> dict:
    """Return current scheduler state and next run times."""
    if scheduler is None:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })

    return {
        "running": scheduler.running,
        "jobs": jobs,
    }


def shutdown_scheduler():
    """Gracefully stop the scheduler."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler: Shut down")
