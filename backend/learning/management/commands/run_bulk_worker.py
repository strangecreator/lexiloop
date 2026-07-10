from __future__ import annotations

import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.utils import timezone

from learning.models import BulkGenerationJob
from learning.services.bulk import process_bulk_job


class Command(BaseCommand):
    help = 'Run the durable LexiLoop bulk-generation worker.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process at most one job and exit.')
        parser.add_argument('--poll-seconds', type=float, default=settings.BULK_WORKER_POLL_SECONDS)

    def handle(self, *args, **options):
        once = options['once']
        poll_seconds = max(0.2, float(options['poll_seconds']))
        self.stdout.write(self.style.SUCCESS('LexiLoop bulk worker started.'))
        while True:
            close_old_connections()
            job = self._claim_job()
            if job is None:
                if once:
                    return
                time.sleep(poll_seconds)
                continue
            self.stdout.write(f'Processing bulk job {job.id} ({job.total_count} terms).')
            process_bulk_job(job.id)
            if once:
                return

    @staticmethod
    def _claim_job():
        stale_before = timezone.now() - timedelta(seconds=settings.BULK_STALE_AFTER_SECONDS)
        with transaction.atomic():
            # A single worker service is expected. select_for_update still makes
            # claiming deterministic if an administrator briefly starts another.
            job = (
                BulkGenerationJob.objects.select_for_update()
                .filter(status=BulkGenerationJob.Status.QUEUED)
                .order_by('created_at')
                .first()
            )
            if job is None:
                job = (
                    BulkGenerationJob.objects.select_for_update()
                    .filter(status=BulkGenerationJob.Status.RUNNING, heartbeat_at__lt=stale_before)
                    .order_by('heartbeat_at')
                    .first()
                )
            if job is None:
                return None
            now = timezone.now()
            job.status = BulkGenerationJob.Status.RUNNING
            job.started_at = job.started_at or now
            job.heartbeat_at = now
            job.error = ''
            job.save(update_fields=['status', 'started_at', 'heartbeat_at', 'error', 'updated_at'])
            return job
