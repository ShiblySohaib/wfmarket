import time

from django.core.management.base import BaseCommand

from market.worker import FetchWorker


class Command(BaseCommand):
    help = "Run the ORM-backed fetch worker thread."

    def handle(self, *args, **options):
        worker = FetchWorker()
        worker.start()
        self.stdout.write(self.style.SUCCESS("Fetch worker started."))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            worker.stop()
            worker.join(timeout=2)
            self.stdout.write(self.style.WARNING("Fetch worker stopped."))
