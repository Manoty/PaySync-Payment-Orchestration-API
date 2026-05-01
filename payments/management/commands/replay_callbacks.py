from django.core.management.base import BaseCommand
from payments.models import CallbackLog
from payments.callback_processor import CallbackProcessor
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Replay unprocessed M-Pesa callbacks stored in CallbackLog"

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of callbacks to replay (default: 50)',
        )
        parser.add_argument(
            '--id',
            type=int,
            help='Replay a specific CallbackLog by ID',
        )

    def handle(self, *args, **options):
        processor = CallbackProcessor()

        if options['id']:
            try:
                log = CallbackLog.objects.get(id=options['id'])
                # Force reprocess even if already processed
                log.processed = False
                log.processing_error = None
                log.save()
                success, message = processor.process(log)
                self.stdout.write(
                    self.style.SUCCESS(f"[{log.id}] {message}")
                    if success else
                    self.style.ERROR(f"[{log.id}] {message}")
                )
            except CallbackLog.DoesNotExist:
                self.stderr.write(f"CallbackLog {options['id']} not found.")
            return

        # Replay all unprocessed
        unprocessed = CallbackLog.objects.filter(
            processed=False,
            processing_error__isnull=False,
        )[:options['limit']]

        count = unprocessed.count()
        self.stdout.write(f"Found {count} unprocessed callbacks to replay.")

        success_count = 0
        fail_count = 0

        for log in unprocessed:
            success, message = processor.process(log)
            if success:
                success_count += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ [{log.id}] {message}"))
            else:
                fail_count += 1
                self.stdout.write(self.style.ERROR(f"  ✗ [{log.id}] {message}"))

        self.stdout.write(
            f"\nDone: {success_count} succeeded, {fail_count} failed."
        )