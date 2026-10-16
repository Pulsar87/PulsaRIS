"""Management command: rebuild the Django mirror from the archive.

Usage: python manage.py pacs_replay [--limit N]
Idempotent; safe to run after missed events or deployment failures
(PACS plan Phase 2 acceptance: replay/rebuild must repair the mirror).
"""

from django.core.management.base import BaseCommand, CommandError

from pacs.orthanc_client import OrthancClient, OrthancUnavailable
from pacs.services import replay_all_studies


class Command(BaseCommand):
    help = "Rebuild/reconcile the PACS metadata mirror from the Orthanc archive."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options):
        client = OrthancClient()
        if not client.is_alive():
            raise CommandError("Orthanc archive is unreachable")
        try:
            result = replay_all_studies(client=client, limit=options["limit"])
        except OrthancUnavailable as exc:
            raise CommandError(f"archive became unavailable during replay: {exc}")
        self.stdout.write(
            self.style.SUCCESS(
                "total={total} synced={synced} errors={errors}".format(**result)
            )
        )
