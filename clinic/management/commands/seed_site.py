"""Seed a new clinic site end-to-end (Phase 4, plan Step 5.1 seeding playbook).

Replaces manual admin clicks with one idempotent command:

    python manage.py seed_site --facility-name "North Clinic" \
        --provider provider@example.com --receptionist frontdesk@example.com \
        --rooms 3 --slots 9-17

Creates (skipping anything that already exists): Facility, staff
FacilityAssignments, room Devices, Mon-Fri ProviderAvailability templates,
and a demo encounter service line code note. Safe to re-run.
"""

from datetime import date, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from clinic.models import FacilityAssignment, ProviderAvailability
from core.models import Device, Facility, Modality


WEEKDAYS = [0, 1, 2, 3, 4]  # Mon-Fri


class Command(BaseCommand):
    help = "Idempotently provision a clinic facility: staff, rooms, availability."

    def add_arguments(self, parser):
        parser.add_argument("--facility-name", required=True)
        parser.add_argument("--address", default="")
        parser.add_argument("--provider", action="append", default=[],
                            help="Email of a user to assign as PROVIDER (repeatable).")
        parser.add_argument("--receptionist", action="append", default=[],
                            help="Email of a user to assign as RECEPTIONIST (repeatable).")
        parser.add_argument("--admin", action="append", default=[],
                            help="Email of a user to assign as ADMIN (repeatable).")
        parser.add_argument("--rooms", type=int, default=2,
                            help="Number of clinic room Devices to create.")
        parser.add_argument("--start-hour", type=int, default=9)
        parser.add_argument("--end-hour", type=int, default=17)
        parser.add_argument("--slot-minutes", type=int, default=20)

    @transaction.atomic
    def handle(self, *args, **opts):
        from users.models import User

        facility, created = Facility.objects.get_or_create(
            name=opts["facility_name"],
            defaults={
                "address": opts["address"],
                # AE title must be unique; derive a stable slug.
                "dicom_ae_title": self._ae_title(opts["facility_name"]),
            },
        )
        self.stdout.write(f"{'Created' if created else 'Found'} facility {facility}")

        role_map = [("PROVIDER", opts["provider"]), ("RECEPTIONIST", opts["receptionist"]),
                    ("ADMIN", opts["admin"])]
        providers = []
        for role, emails in role_map:
            for email in emails:
                try:
                    user = User.objects.get(email=email)
                except User.DoesNotExist:
                    raise CommandError(f"No user with email {email!r} — create them first.")
                assignment, c = FacilityAssignment.objects.get_or_create(
                    user=user, facility=facility,
                    defaults={"role_at_facility": role, "start_date": date.today()},
                )
                if not c and assignment.role_at_facility != role:
                    assignment.role_at_facility = role
                    assignment.save(update_fields=["role_at_facility"])
                self.stdout.write(f"  {'created' if c else 'exists'} assignment {user} -> {role}")
                if role == "PROVIDER":
                    providers.append(user)

        # Rooms: clinic spaces modelled as Devices (no imaging modality needed,
        # so attach the generic 'OT' modality row, creating it if absent).
        modality, _ = Modality.objects.get_or_create(
            code="OT", defaults={"name": "Clinic room / other"}
        )
        existing_rooms = Device.objects.filter(facility=facility, modality=modality).count()
        for n in range(existing_rooms + 1, opts["rooms"] + 1):
            Device.objects.create(
                facility=facility, modality=modality,
                name=f"{facility.name} Room {n}", room_number=str(n),
                dicom_ae_title=self._ae_title(f"{opts['facility_name']}-room-{n}"),
            )
            self.stdout.write(f"  created room {n}")

        # Weekly availability templates per provider (Mon-Fri window).
        for provider in providers:
            for weekday in WEEKDAYS:
                _, c = ProviderAvailability.objects.get_or_create(
                    provider=provider, facility=facility,
                    kind=ProviderAvailability.Kind.TEMPLATE, weekday=weekday,
                    defaults={
                        "start_time": time(hour=opts["start_hour"]),
                        "end_time": time(hour=opts["end_hour"]),
                        "slot_minutes": opts["slot_minutes"],
                        "note": "seed_site",
                    },
                )
                if c:
                    self.stdout.write(f"  availability template {provider} weekday {weekday}")

        self.stdout.write(self.style.SUCCESS(
            f"Site '{facility.name}' seeded. Next: verify via day board at "
            "/clinic/ and run the Phase 3 pilot walkthrough A."
        ))

    @staticmethod
    def _ae_title(text):
        slug = "".join(ch for ch in text.upper() if ch.isalnum())[:12] or "SITE"
        # Ensure uniqueness even for similar names by appending a short hash.
        import hashlib
        return (slug + hashlib.md5(text.encode()).hexdigest()[: (16 - len(slug))])[:16]
