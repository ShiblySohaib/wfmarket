import os
import sys

from django.apps import AppConfig


class MarketConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "market"

    def ready(self):
        if "runserver" not in sys.argv:
            return

        # Start worker only in the process that handles requests
        # If reloader is on, that's the child process (RUN_MAIN=true)
        # If reloader is off, it's the only process (RUN_MAIN is unset)
        if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
            # We are in the parent process of a reloader session
            return

        from .worker import FetchWorker
        import threading
        import time

        # Start the fetch worker thread
        worker = FetchWorker()
        worker.start()

        # Background scheduler — queues a new fetch only when idle
        from market.services import (
            get_market_settings,
            get_running_job,
            get_pending_job,
            build_fetch_job,
            enqueue_job,
            clear_stale_fetch_guard,
        )

        def scheduler_loop():
            while True:
                clear_stale_fetch_guard()
                settings = get_market_settings()
                interval = max(int(settings.auto_refresh_interval or 120), 30)
                
                from market.services import set_next_fetch_at, _scheduler_interrupt
                set_next_fetch_at(time.time() + interval)
                
                # Wait for interval or interrupt
                if _scheduler_interrupt.wait(timeout=interval):
                    _scheduler_interrupt.clear()
                    # Interrupted by a manual refresh! Loop immediately.
                    continue

                # Enqueue if nothing is pending (allows 1 in queue if another is running)
                try:
                    from market.services import is_labels_sync_active
                    if not get_pending_job() and not is_labels_sync_active():
                        job = build_fetch_job(created_by="background")
                        enqueue_job(job)
                except Exception:
                    pass

        threading.Thread(target=scheduler_loop, daemon=True).start()

        # Startup fetch
        try:
            from .fetch_api import enqueue_startup_fetch
            enqueue_startup_fetch(created_by="foreground")
        except Exception:
            pass