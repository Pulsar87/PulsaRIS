"""Management command: one-shot drain of the Orthanc changes feed.

Usage: python manage.py pacs_sync [--limit N]
"""

from django.core.management.base import BaseCommand, CommandError

from pacs.orthanc_client import OrthancClient, OrthancUnavailable
from pacs.services import process_changes


class Command(BaseCommand):
    help = "Synchronize archived study metadata into the Django PACS mirror."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        client = OrthancClient()
        if not client.is_alive():
            raise CommandError(
                "Orthanc archive is unreachable; check ORTHANC_API_URL and service health"
            )
        try:
            counters = process_changes(client=client, limit=options["limit"])
        except OrthancUnavailable as exc:
            raise CommandError(f"archive became unavailable mid-sync: {exc}")
        self.stdout.write(
            self.style.SUCCESS(
                "fetched={fetched} processed={processed} failed={failed} "
                "ignored={ignored}".format(**counters)
            )
        )
