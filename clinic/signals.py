"""Phase 3 interoperability hooks: transactional outbox emitters.

Design (plan Step 4 item 2): business events are captured as
``clinic.IntegrationEvent`` rows via post_save on Appointment/Encounter, in
the *same transaction* as the state change (Django post_save fires inside
``@transaction.atomic`` blocks of the service functions in
``clinic.scheduling``). Consumers (HL7 v2 / FHIR R4 mappers) poll
``delivered_at IS NULL`` — consumer wiring is intentionally deferred until
pilot feedback per addendum C Phase 3.

Guards:
- events fire only on meaningful status transitions (created flag or changed
  DB value), never on unrelated saves;
- payload is a minimal stable snapshot (ids + timestamps + status); no PHI
  beyond identifiers — full demographics stay behind the API boundary.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from clinic.models import Appointment, Encounter, IntegrationEvent


def _emit(event_type, *, facility_id, entity_type, entity_id, payload):
    IntegrationEvent.objects.create(
        event_type=event_type,
        facility_id=facility_id,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )


@receiver(post_save, sender=Appointment)
def appointment_outbox(sender, instance, created, **kwargs):
    if created:
        _emit(
            IntegrationEvent.EventType.APPOINTMENT_BOOKED,
            facility_id=instance.facility_id,
            entity_type="Appointment",
            entity_id=instance.pk,
            payload={
                "appointment": str(instance.pk),
                "patient": str(instance.patient_id),
                "provider": str(instance.provider_id) if instance.provider_id else None,
                "start_datetime": instance.start_datetime.isoformat(),
                "duration_minutes": instance.duration_minutes,
                "status": instance.status,
            },
        )
        return
    # Emit at most once per appointment per event type (dedup guard keeps the
    # outbox clean even if an object is re-saved after the transition).
    if instance.status == Appointment.Status.CANCELLED and instance.cancelled_at:
        if not _already_emitted("Appointment", instance.pk,
                                IntegrationEvent.EventType.APPOINTMENT_CANCELLED):
            _emit(
                IntegrationEvent.EventType.APPOINTMENT_CANCELLED,
                facility_id=instance.facility_id,
                entity_type="Appointment",
                entity_id=instance.pk,
                payload={
                    "appointment": str(instance.pk),
                    "patient": str(instance.patient_id),
                    "reason": instance.cancelled_reason,
                    "cancelled_at": instance.cancelled_at.isoformat(),
                },
            )
    elif instance.status == Appointment.Status.COMPLETED:
        if not _already_emitted("Appointment", instance.pk,
                                IntegrationEvent.EventType.APPOINTMENT_COMPLETED):
            _emit(
                IntegrationEvent.EventType.APPOINTMENT_COMPLETED,
                facility_id=instance.facility_id,
                entity_type="Appointment",
                entity_id=instance.pk,
                payload={
                    "appointment": str(instance.pk),
                    "patient": str(instance.patient_id),
                    "completed_at": instance.updated_at.isoformat(),
                },
            )


def _already_emitted(entity_type, entity_id, event_type):
    return IntegrationEvent.objects.filter(
        entity_type=entity_type, entity_id=entity_id, event_type=event_type
    ).exists()


@receiver(post_save, sender=Encounter)
def encounter_outbox(sender, instance, created, update_fields, **kwargs):
    """Emit ENCOUNTER_CLOSED exactly once, when ended_at first appears."""
    if created or (update_fields is not None and "ended_at" not in update_fields):
        return
    if instance.status != Encounter.VisitStatus.COMPLETED or not instance.ended_at:
        return
    already = IntegrationEvent.objects.filter(
        entity_type="Encounter",
        entity_id=instance.pk,
        event_type=IntegrationEvent.EventType.ENCOUNTER_CLOSED,
    ).exists()
    if already:
        return
    _emit(
        IntegrationEvent.EventType.ENCOUNTER_CLOSED,
        facility_id=instance.facility_id,
        entity_type="Encounter",
        entity_id=instance.pk,
        payload={
            "encounter": str(instance.pk),
            "patient": str(instance.patient_id),
            "provider": str(instance.provider_id) if instance.provider_id else None,
            "started_at": instance.started_at.isoformat() if instance.started_at else None,
            "ended_at": instance.ended_at.isoformat(),
        },
    )
