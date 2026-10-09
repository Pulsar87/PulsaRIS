"""Flush the IntegrationEvent outbox (Phase 4, plan Step 5.2).

    python manage.py flush_outbox [--limit 100]

Wraps clinic.outbox.deliver_pending; intended for cron / celery-beat, never
the request path. Exits non-zero when dead-letters were produced so a
monitoring system can alarm on backlog poisoning.
"""

from django.core.management.base import BaseCommand

from clinic.outbox import backlog_depth, deliver_pending


class Command(BaseCommand):
    help = "Deliver pending IntegrationEvent rows (HL7 ADT export)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **opts):
        delivered, dead = deliver_pending(limit=opts["limit"])
        remaining = backlog_depth()
        self.stdout.write(
            f"outbox: delivered={delivered} dead_lettered={dead} remaining_backlog={remaining}"
        )
        if dead:
            raise SystemExit(2)
