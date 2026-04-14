import time

from django.core.management.base import BaseCommand

from market.services import (
    build_fetch_job,
    clear_stale_fetch_guard,
    enqueue_job,
    get_market_settings,
    get_pending_job,
    get_running_job,
)


class Command(BaseCommand):
    help = "Schedule background fetch jobs using the configured auto refresh interval."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Background fetch scheduler started."))
        while True:
            clear_stale_fetch_guard()
            settings_obj = get_market_settings()
            
            # The client-side dashboard also manages background fetch timings when open.
            # On the server side, we act as a safety net if no dashboard is open.
            # We ONLY enqueue if absolutely nothing is running/pending.
            running_job = get_running_job()
            pending_job = get_pending_job()
            
            if not running_job and not pending_job:
                job = build_fetch_job(created_by="background_auto")
                queued_job = enqueue_job(job, pending=False)
                self.stdout.write("Scheduled background fetch %s" % queued_job.session_id)
            elif running_job and not pending_job:
                # We want maximum ONE background fetch in queue during an ongoing fetch
                job = build_fetch_job(created_by="background_auto")
                queued_job = enqueue_job(job, pending=True)
                self.stdout.write("Queued background fetch %s" % queued_job.session_id)
                
            time.sleep(max(int(settings_obj.auto_refresh_interval or 120), 1))
