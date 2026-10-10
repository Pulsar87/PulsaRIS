"""Clinic module tests — encodes plan Verification items 1-5.

Phase 0 covers: facility-scoped access with shared patient identity (1),
cross-module schema links for encounter billing & appointments (4, structural),
migrations/checks (5). Items 2-3 (conflict engine transitions, note signing)
land with Phases 1-2; the corresponding test classes are stubbed below.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog
from billing.models import PatientAccount, ServiceLine
from clinic.models import (
    Appointment,
    Encounter,
    EncounterNote,
    FacilityAssignment,
    IntegrationEvent,
    PatientFacilityIdentifier,
    PatientMergeLog,
    ProviderAvailability,
    RoomBooking,
    Vitals,
)
from clinic.permissions import accessible_facility_ids, has_facility_access
from core.models import Facility
from orders.models import ExamOrder
from patients.models import Patient
from users.models import User


def scoped_rows(user):
    """Exercise the shared facility-scoping filter (core.mixins policy) against
    a real clinic table, as a stand-in for any FacilityScopedModel subclass."""
    from clinic.permissions import accessible_facility_ids

    ids = accessible_facility_ids(user)
    qs = Encounter.objects.all()
    if ids is None:
        return qs
    return qs.filter(facility_id__in=ids)


def make_patient(mrn):
    return Patient.objects.create(
        mrn=mrn,
        first_name_en="Test",
        last_name_en="Patient",
        dob=date(1990, 1, 1),
        gender="M",
    )


def make_user(email, facility=None, username=None):
    return User.objects.create_user(
        username=username or email.split("@")[0], email=email, password="pw", facility=facility
    )


class FacilityScopingTests(TestCase):
    """Verification item 1: records facility-scoped, patient identity shared."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.f2 = Facility.objects.create(name="Site B", dicom_ae_title="AE_B")
        self.f3 = Facility.objects.create(name="Site C", dicom_ae_title="AE_C")
        self.user = make_user("staff@test.com", facility=self.f1)
        self.patient = make_patient("MRN-001")
        for f in (self.f1, self.f2, self.f3):
            Encounter.objects.create(patient=self.patient, facility=f)

    def test_home_facility_only(self):
        rows = scoped_rows(self.user)
        self.assertEqual([r.facility_id for r in rows], [self.f1.pk])

    def test_assignment_grants_second_site(self):
        FacilityAssignment.objects.create(
            user=self.user, facility=self.f2, role_at_facility="RECEPTIONIST",
            start_date=date.today(),
        )
        ids = accessible_facility_ids(self.user)
        self.assertEqual(ids, {self.f1.pk, self.f2.pk})
        self.assertTrue(has_facility_access(self.user, self.f2.pk))
        self.assertFalse(has_facility_access(self.user, self.f3.pk))
        self.assertEqual(scoped_rows(self.user).count(), 2)

    def test_expired_assignment_not_counted(self):
        FacilityAssignment.objects.create(
            user=self.user, facility=self.f2, role_at_facility="PROVIDER",
            start_date=date(2020, 1, 1), end_date=date(2020, 12, 31),
        )
        self.assertEqual(accessible_facility_ids(self.user), {self.f1.pk})

    def test_deactivated_assignment_not_counted(self):
        FacilityAssignment.objects.create(
            user=self.user, facility=self.f2, role_at_facility="PROVIDER",
            start_date=date.today(), is_active=False,
        )
        self.assertEqual(accessible_facility_ids(self.user), {self.f1.pk})

    def test_superuser_unrestricted(self):
        root = User.objects.create_superuser(
            username="root", email="root@test.com", password="pw"
        )
        self.assertIsNone(accessible_facility_ids(root))
        self.assertEqual(scoped_rows(root).count(), 3)

    def test_shared_patient_identity_with_site_identifiers(self):
        """One Patient row; per-site chart numbers via join table."""
        PatientFacilityIdentifier.objects.create(
            patient=self.patient, facility=self.f1, identifier="A-1001"
        )
        PatientFacilityIdentifier.objects.create(
            patient=self.patient, facility=self.f2, identifier="B-77", identifier_type="CHART"
        )
        self.assertEqual(Patient.objects.filter(pk=self.patient.pk).count(), 1)
        self.assertEqual(self.patient.facility_identifiers.count(), 2)

    def test_identifier_unique_per_site(self):
        PatientFacilityIdentifier.objects.create(
            patient=self.patient, facility=self.f1, identifier="DUP"
        )
        other = make_patient("MRN-002")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PatientFacilityIdentifier.objects.create(
                    patient=other, facility=self.f1, identifier="DUP"
                )

    def test_one_primary_identifier_per_site(self):
        PatientFacilityIdentifier.objects.create(
            patient=self.patient, facility=self.f1, identifier="P1", is_primary=True
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PatientFacilityIdentifier.objects.create(
                    patient=self.patient, facility=self.f1, identifier="P2", is_primary=True
                )

    def test_audit_log_admin_is_read_only(self):
        from django.contrib import admin as dj_admin
        from django.test import RequestFactory

        ma = dj_admin.site._registry[AuditLog]
        request = RequestFactory().get("/")
        request.user = make_user("auditor@test.com")
        self.assertFalse(ma.has_add_permission(request))
        self.assertFalse(ma.has_change_permission(request))
        self.assertFalse(ma.has_delete_permission(request))


class ServiceLineSourceExclusivityTests(TestCase):
    """Verification item 4 (structural): encounter charges coexist with RIS
    exam-order charges without changing existing billing semantics."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.patient = make_patient("MRN-100")
        self.account = PatientAccount.objects.create(
            patient=self.patient, account_number="ACC-100"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, facility=self.f1, reason="consult"
        )

    def _make_exam_order(self):
        from core.models import Modality
        from orders.models import ExamOrder

        mod = Modality.objects.create(code="CT")
        return ExamOrder.objects.create(
            patient=self.patient,
            facility=self.f1,
            accession_number="A-1",
            modality=mod,
            procedure_code="70000",
            procedure_name_en="Consultation",
        )

    def _line_kwargs(self):
        return dict(
            patient_account=self.account,
            service_date=date.today(),
            procedure_code="99213",
            procedure_name="Office visit",
            unit_price=Decimal("100.00"),
            total_charge=Decimal("100.00"),
        )

    def test_exam_order_line_still_valid(self):
        line = ServiceLine.objects.create(exam_order=self._make_exam_order(), **self._line_kwargs())
        self.assertIsNotNone(line.pk)

    def test_encounter_line_valid(self):
        line = ServiceLine.objects.create(encounter=self.encounter, **self._line_kwargs())
        self.assertEqual(self.encounter.service_lines.count(), 1)

    def test_both_sources_rejected(self):
        # ServiceLine.save() raises ValidationError for dual sources; the DB
        # CheckConstraint is the backstop for raw SQL/bulk writes.
        with self.assertRaises(ValidationError):
            ServiceLine.objects.create(
                exam_order=self._make_exam_order(), encounter=self.encounter,
                **self._line_kwargs(),
            )

    def test_neither_source_rejected(self):
        with self.assertRaises(ValidationError):
            ServiceLine.objects.create(**self._line_kwargs())


class AppointmentEncounterLinkTests(TestCase):
    """Verification item 2/4 (structural): appointment <-> order/encounter links."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.patient = make_patient("MRN-200")
        self.provider = make_user("dr@test.com", facility=self.f1)

    def test_appointment_window_and_links(self):
        start = timezone.make_aware(datetime(2026, 10, 20, 9, 0))
        appt = Appointment.objects.create(
            patient=self.patient, facility=self.f1, provider=self.provider,
            start_datetime=start, duration_minutes=30,
        )
        self.assertEqual(appt.end_datetime, start + timedelta(minutes=30))

        enc = Encounter.objects.create(
            patient=self.patient, facility=self.f1, appointment=appt
        )
        self.assertEqual(appt.encounters.first(), enc)

        from core.models import Modality
        from orders.models import ExamOrder

        order = ExamOrder.objects.create(
            patient=self.patient, facility=self.f1, accession_number="A-200",
            modality=Modality.objects.create(code="US"), procedure_code="76000",
            procedure_name_en="US exam", appointment=appt,
        )
        self.assertEqual(list(appt.exam_orders.all()), [order])

    def test_encounter_defaults_to_planned_visit_status(self):
        enc = Encounter.objects.create(patient=self.patient, facility=self.f1)
        self.assertEqual(enc.status, Encounter.VisitStatus.PLANNED)


def next_weekday_slot(weekday=0, hour=9, minute=0):
    """A future datetime on the given weekday (0=Mon) at hour:minute."""
    today = timezone.localdate()
    delta = (weekday - today.weekday()) % 7 or 7
    naive = datetime.combine(today + timedelta(days=delta), datetime.min.time())
    naive = naive.replace(hour=hour, minute=minute)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


class SchedulingTransitionTests(TestCase):
    """Verification item 2: state machine transitions."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.patient = make_patient("MRN-300")

    def test_cancel_records_reason(self):
        appt = Appointment.objects.create(
            patient=self.patient, facility=self.f1,
            start_datetime=timezone.now() + timedelta(days=1),
            status=Appointment.Status.CANCELLED, cancelled_reason="patient request",
        )
        self.assertEqual(appt.cancelled_reason, "patient request")

    def test_illegal_transition_rejected(self):
        from clinic.models import Appointment as A

        appt = A.objects.create(
            patient=self.patient, facility=self.f1,
            start_datetime=timezone.now() + timedelta(days=1),
        )
        # BOOKED -> COMPLETED skips required check-in; must be rejected.
        with self.assertRaises(ValidationError):
            appt.transition_to(A.Status.COMPLETED)
        # Legal path: BOOKED -> CHECKED_IN -> COMPLETED, then terminal.
        appt.transition_to(A.Status.CHECKED_IN)
        appt.transition_to(A.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            appt.transition_to(A.Status.BOOKED)  # COMPLETED is terminal


class ConflictEngineTests(TestCase):
    """Verification item 2 (Phase 3 close-out): unified availability/conflict
    engine edge cases — provider double-book, half-open windows, day-off
    exceptions, room conflicts, and the RIS exam-slot adapter."""

    def setUp(self):
        from core.models import Device, Modality
        from clinic import scheduling

        self.scheduling = scheduling
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.f2 = Facility.objects.create(name="Site B", dicom_ae_title="AE_B")
        self.provider = make_user("dr@clinic.test")
        self.patient = make_patient("MRN-CE1")
        self.other_patient = make_patient("MRN-CE2")
        self.start = next_weekday_slot(weekday=0, hour=9)
        ProviderAvailability.objects.create(
            provider=self.provider, facility=self.f1, kind="TEMPLATE",
            weekday=self.start.weekday(), start_time=self.start.time(),
            end_time=(self.start + timedelta(hours=4)).time(), slot_minutes=20,
        )
        self.modality = Modality.objects.create(code="US", name="Ultrasound")
        self.device = Device.objects.create(
            name="US Room 1", modality=self.modality, facility=self.f1,
            dicom_host="10.0.0.1",
        )

    def _book(self, patient, start=None, duration=20, provider=None, room=None):
        return self.scheduling.book_appointment(
            patient=patient, facility=self.f1, start=start or self.start,
            duration_minutes=duration, provider=provider or self.provider, room=room,
        )

    def test_book_within_availability_window(self):
        appt = self._book(self.patient)
        self.assertEqual(appt.status, Appointment.Status.BOOKED)

    def test_provider_double_booking_rejected(self):
        self._book(self.patient)
        with self.assertRaises(ValidationError) as ctx:
            self._book(self.other_patient)  # same provider, same time
        self.assertTrue(any("conflict" in str(e).lower() for e in ctx.exception.messages))

    def test_touching_windows_allowed_half_open(self):
        self._book(self.patient, duration=20)
        appt2 = self._book(self.other_patient, start=self.start + timedelta(minutes=20))
        self.assertIsNotNone(appt2.pk)  # 09:20 start after 09:00-09:20 booking is OK

    def test_outside_availability_window_rejected(self):
        with self.assertRaises(ValidationError):
            self._book(self.patient, start=self.start + timedelta(hours=5))

    def test_day_off_exception_blocks_booking(self):
        ProviderAvailability.objects.create(
            provider=self.provider, facility=self.f1, kind="EXCEPTION",
            exception_date=self.start.date(), is_available=False,
        )
        with self.assertRaises(ValidationError):
            self._book(self.patient)

    def test_room_conflict_between_clinic_and_exam_order(self):
        """Addendum B.1/B.2: RIS exam slots reserve through the SAME engine."""
        from orders.models import ExamOrder

        self._book(self.patient, room=self.device)
        order = ExamOrder.objects.create(
            patient=self.other_patient, facility=self.f1, accession_number="ACC-CE-1",
            modality=self.modality, procedure_code="US-01", procedure_name_en="Abdomen US",
        )
        with self.assertRaises(ValidationError):
            self.scheduling.reserve_exam_slot(order, start=self.start, room=self.device)
        # reserving a free slot works and marks the order scheduled
        self.scheduling.reserve_exam_slot(
            order, start=self.start + timedelta(hours=1), room=self.device
        )
        order.refresh_from_db()
        self.assertEqual(order.status, ExamOrder.Status.SCHEDULED)
        self.assertEqual(RoomBooking.objects.filter(room=self.device).count(), 2)
        # cancelling the exam frees its hold
        self.scheduling.release_exam_slot(order)
        rb = RoomBooking.objects.get(exam_order=order)
        self.assertTrue(rb.is_cancelled)


class EncounterLifecycleTests(TestCase):
    """Verification item 3 (close-out): encounter state machine + doc minimum."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.patient = make_patient("MRN-EL1")
        self.provider = make_user("dr2@clinic.test")

    def _encounter(self):
        return Encounter.objects.create(
            patient=self.patient, facility=self.f1, provider=self.provider,
            reason="follow-up",
        )

    def test_requires_provider_to_start(self):
        enc = Encounter.objects.create(patient=self.patient, facility=self.f1)
        with self.assertRaises(ValidationError):
            enc.start()

    def test_complete_without_documentation_rejected(self):
        from clinic import scheduling

        enc = self._encounter()
        scheduling.start_encounter(enc, actor=self.provider)
        with self.assertRaises(ValidationError) as ctx:
            scheduling.complete_encounter(enc, actor=self.provider)
        msg = "; ".join(str(m) for m in ctx.exception.messages)
        self.assertIn("signed encounter note", msg)
        self.assertIn("vitals", msg)

    def test_full_lifecycle_with_documentation(self):
        from clinic import scheduling

        enc = self._encounter()
        scheduling.start_encounter(enc, actor=self.provider)
        Vitals.objects.create(encounter=enc, recorded_by=self.provider, systolic_bp=120, diastolic_bp=80)
        note = EncounterNote.objects.create(encounter=enc, author=self.provider, body="Assessment ok.")
        scheduling.sign_note(note, signing_user=self.provider)
        scheduling.complete_encounter(enc, actor=self.provider)
        enc.refresh_from_db()
        self.assertEqual(enc.status, Encounter.VisitStatus.COMPLETED)
        self.assertIsNotNone(enc.ended_at)

    def test_completed_is_terminal(self):
        enc = self._encounter()
        enc.status = Encounter.VisitStatus.COMPLETED
        with self.assertRaises(ValidationError):
            enc.cancel(reason="too late")

    def test_business_audit_rows_written(self):
        from audit.models import AuditLog
        from clinic import scheduling

        enc = self._encounter()
        scheduling.start_encounter(enc, actor=self.provider)
        self.assertTrue(
            AuditLog.objects.filter(entity_type="Encounter", entity_id=str(enc.pk),
                                    action="CLINIC_ENC_START").exists()
        )


class NoteSigningImmutabilityTests(TestCase):
    """Verification item 3: append-only versions + SHA-256 hash chain."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.patient = make_patient("MRN-NS1")
        self.author = make_user("author@clinic.test")
        self.other = make_user("other@clinic.test")
        self.enc = Encounter.objects.create(
            patient=self.patient, facility=self.f1, provider=self.author,
        )

    def _note(self, body="Initial assessment."):
        # first note for the encounter is v1; later ones append a version
        nxt = self.enc.notes.order_by("-version").values_list("version", flat=True).first()
        return EncounterNote.objects.create(encounter=self.enc, author=self.author,
                                            body=body, version=(nxt or 0) + 1)

    def test_only_author_can_sign(self):
        note = self._note()
        with self.assertRaises(ValidationError):
            note.sign(self.other)

    def test_signed_note_body_edit_blocked_at_orm(self):
        note = self._note()
        note.sign(self.author)
        note.body = "tampered"
        with self.assertRaises(ValidationError):
            note.save()

    def test_signed_note_cannot_be_deleted(self):
        note = self._note()
        note.sign(self.author)
        with self.assertRaises(ValidationError):
            note.delete()

    def test_amendment_creates_chained_version(self):
        from clinic import scheduling

        v1 = self._note()
        v1.sign(self.author)
        v2 = scheduling.amend_note(v1, body="Corrected dose.", author=self.author)
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.supersedes_id, v1.pk)
        self.assertEqual(v2.prev_version_hash, v1.content_hash)
        v2.sign(self.author)
        self.assertTrue(v2.verify_integrity())
        # drafts cannot be superseded — only signed notes can
        draft = self._note(body="draft")
        with self.assertRaises(ValidationError):
            draft.next_version(body="nope", author=self.author)

    def test_tampering_breaks_chain_detection(self):
        v1 = self._note()
        v1.sign(self.author)
        v2 = v1.next_version(body="v2", author=self.author)
        v2.sign(self.author)
        # simulate DB-level tampering bypassing pre_save guard
        EncounterNote.objects.filter(pk=v1.pk).update(content_hash="0" * 64)
        v2.refresh_from_db()
        self.assertFalse(v2.verify_integrity())


class EncounterBillingIntegrationTests(TestCase):
    """Verification item 4: encounter-sourced ServiceLine bills correctly."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.patient = make_patient("MRN-BL1")
        self.provider = make_user("bill-dr@clinic.test")
        self.account = PatientAccount.objects.create(patient=self.patient)

    def test_bill_encounter_service_creates_line(self):
        from clinic import scheduling

        enc = Encounter.objects.create(patient=self.patient, facility=self.f1,
                                       provider=self.provider)
        line = scheduling.bill_encounter_service(
            enc, code="CONS-01", name="Consultation",
            unit_price=Decimal("50.00"), rendering_provider=self.provider,
            created_by=self.provider,
        )
        self.assertEqual(line.encounter_id, enc.pk)
        self.assertIsNone(line.exam_order_id)  # XOR constraint satisfied
        line.refresh_from_db()
        self.assertEqual(line.total_charge, Decimal("50.00"))
        self.assertEqual(line.patient_account_id, self.account.pk)

    def test_exam_order_source_still_works(self):
        """RIS billing path untouched by the encounter link (addendum A.1)."""
        from core.models import Modality
        from orders.models import ExamOrder

        mod = Modality.objects.create(code="CT", name="CT")
        order = ExamOrder.objects.create(
            patient=self.patient, facility=self.f1, accession_number="ACC-BL-1",
            modality=mod, procedure_code="CT-01", procedure_name_en="Head CT",
        )
        line = ServiceLine.objects.create(
            patient_account=self.account, exam_order=order, procedure_code="CT-01",
            procedure_name="Head CT", unit_price=Decimal("200.00"), quantity=1,
            total_charge=Decimal("200.00"), service_date=date.today(),
        )
        self.assertEqual(line.total_charge, Decimal("200.00"))
        self.assertIsNone(line.encounter_id)  # XOR holds on the RIS side too


class IntegrationOutboxTests(TestCase):
    """Phase 3: transactional outbox emits one row per business event."""

    def setUp(self):
        from clinic import scheduling

        self.scheduling = scheduling
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.patient = make_patient("MRN-OB1")
        self.provider = make_user("ob-dr@clinic.test")
        self.start = next_weekday_slot(weekday=2, hour=10)
        ProviderAvailability.objects.create(
            provider=self.provider, facility=self.f1, kind="TEMPLATE",
            weekday=self.start.weekday(), start_time=self.start.time(),
            end_time=(self.start + timedelta(hours=3)).time(),
        )

    def test_book_emits_event(self):
        appt = self.scheduling.book_appointment(
            patient=self.patient, facility=self.f1, start=self.start,
            provider=self.provider,
        )
        ev = IntegrationEvent.objects.filter(
            event_type=IntegrationEvent.EventType.APPOINTMENT_BOOKED,
            entity_id=appt.pk,
        )
        self.assertTrue(ev.exists())
        self.assertIsNone(ev.first().delivered_at)

    def test_cancel_emits_event_once(self):
        appt = self.scheduling.book_appointment(
            patient=self.patient, facility=self.f1, start=self.start,
            provider=self.provider,
        )
        self.scheduling.cancel_appointment(appt, reason="sick")
        appt.save()  # re-save must not duplicate the event
        self.assertEqual(
            IntegrationEvent.objects.filter(
                event_type=IntegrationEvent.EventType.APPOINTMENT_CANCELLED,
                entity_id=appt.pk,
            ).count(),
            1,
        )

    def test_encounter_close_emits_event(self):
        appt = self.scheduling.book_appointment(
            patient=self.patient, facility=self.f1, start=self.start,
            provider=self.provider,
        )
        _, enc = self.scheduling.check_in_appointment(appt)
        Vitals.objects.create(encounter=enc, systolic_bp=110, diastolic_bp=70)
        note = EncounterNote.objects.create(encounter=enc, author=self.provider,
                                            body="done")
        self.scheduling.sign_note(note, signing_user=self.provider)
        self.scheduling.complete_encounter(enc, actor=self.provider)
        self.assertTrue(IntegrationEvent.objects.filter(
            event_type=IntegrationEvent.EventType.ENCOUNTER_CLOSED,
            entity_id=enc.pk,
        ).exists())


class ClinicApiTests(TestCase):
    """Phase 3: read-only /api/clinic/ endpoints are facility-scoped & GET-only."""

    def setUp(self):
        from datetime import date as _date

        from clinic import scheduling
        from license.models import LicenseActivation

        # LicenseMiddleware redirects any non-exempt request to the activation
        # page when no LicenseActivation row exists — seed a valid one so the
        # API under test is actually reached.
        LicenseActivation.objects.create(
            pk=1, expiry_date=_date.today() + timedelta(days=365),
            signature="TESTSIG", max_orders=None,
        )

        self.scheduling = scheduling
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.f2 = Facility.objects.create(name="Site B", dicom_ae_title="AE_B")
        self.patient = make_patient("MRN-API1")
        self.provider = make_user("api-dr@clinic.test")
        self.user = make_user("api-user@clinic.test", facility=self.f1)
        # Phase 4 rollout flag: f1 must be live for gated API/HTML requests.
        FacilityAssignment.objects.create(
            user=self.user, facility=self.f1, role_at_facility="ADMIN",
            start_date=_date.today() - timedelta(days=1),
        )
        self.start = next_weekday_slot(weekday=4, hour=9)
        ProviderAvailability.objects.create(
            provider=self.provider, facility=self.f1, kind="TEMPLATE",
            weekday=self.start.weekday(), start_time=self.start.time(),
            end_time=(self.start + timedelta(hours=3)).time(),
        )
        self.appt = self.scheduling.book_appointment(
            patient=self.patient, facility=self.f1, start=self.start,
            provider=self.provider,
        )
        self.foreign_appt = Appointment.objects.create(
            patient=make_patient("MRN-API2"), facility=self.f2,
            start_datetime=self.start,
        )

    def _get(self, url):
        self.client.force_login(self.user)
        return self.client.get(url)

    def test_appointments_scoped_to_home_facility(self):
        resp = self._get("/api/clinic/appointments/")
        self.assertEqual(resp.status_code, 200)
        # global DRF PageNumberPagination -> envelope with "results"
        payload = resp.json()
        results = payload.get("results", payload)
        ids = [r["id"] for r in results]
        self.assertIn(str(self.appt.pk), ids)
        self.assertNotIn(str(self.foreign_appt.pk), ids)

    def test_detail_cross_facility_returns_404(self):
        self.client.force_login(self.user)
        resp = self.client.get(f"/api/clinic/appointments/{self.foreign_appt.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_write_methods_rejected(self):
        self.client.force_login(self.user)
        resp = self.client.post("/api/clinic/appointments/", {})
        self.assertEqual(resp.status_code, 405)

    def test_anonymous_denied(self):
        resp = self.client.get("/api/clinic/patients/")
        self.assertIn(resp.status_code, (401, 403))

    def test_patient_search_scoped(self):
        resp = self._get("/api/clinic/patients/?q=MRN-API1")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual([r["mrn"] for r in results], ["MRN-API1"])
        resp2 = self._get("/api/clinic/patients/?q=MRN-API2")
        self.assertEqual(resp2.json()["results"], [])


class RolloutFlagTests(TestCase):
    """Phase 4 (Step 5.3 rollback plan): per-facility clinic feature flag.

    A site is live only when it has an active, started ADMIN
    FacilityAssignment; disabling that assignment closes every clinic URL for
    non-superusers without a redeploy.
    """

    def setUp(self):
        from license.models import LicenseActivation

        LicenseActivation.objects.create(
            pk=1, expiry_date=date.today() + timedelta(days=365),
            signature="TESTSIG", max_orders=None,
        )
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.staff = make_user("rollout-staff@clinic.test", facility=self.f1)
        self.superuser = User.objects.create_superuser(
            username="rollout-root", email="rollout-root@clinic.test", password="pw"
        )
        # No ADMIN assignment yet -> f1 is NOT rolled out.

    def _enable_site(self):
        return FacilityAssignment.objects.create(
            user=self.staff, facility=self.f1, role_at_facility="ADMIN",
            start_date=date.today() - timedelta(days=1),
        )

    def test_flag_state_transitions(self):
        from clinic import rollout

        self.assertFalse(rollout.facility_clinic_enabled(self.f1.pk))
        a = self._enable_site()
        self.assertTrue(rollout.facility_clinic_enabled(self.f1.pk))
        self.assertIn(self.f1.pk, rollout.enabled_facility_ids())
        # rollback lever 1: deactivate the ADMIN assignment
        a.is_active = False
        a.save()
        self.assertFalse(rollout.facility_clinic_enabled(self.f1.pk))
        # rollback lever 2: future start date keeps the site closed
        a.is_active = True
        a.start_date = date.today() + timedelta(days=1)
        a.save()
        self.assertFalse(rollout.facility_clinic_enabled(self.f1.pk))

    def test_ui_denied_for_disabled_site(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/clinic/appointments/")
        self.assertEqual(resp.status_code, 403)

    def test_ui_allowed_once_site_live(self):
        self._enable_site()
        self.client.force_login(self.staff)
        resp = self.client.get("/clinic/appointments/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_view_gated_on_object_facility(self):
        appt = Appointment.objects.create(
            patient=make_patient("MRN-RO1"), facility=self.f1,
            start_datetime=next_weekday_slot(),
        )
        self.client.force_login(self.staff)
        resp = self.client.get(f"/clinic/appointments/{appt.pk}/")
        self.assertEqual(resp.status_code, 403)
        self._enable_site()
        resp = self.client.get(f"/clinic/appointments/{appt.pk}/")
        self.assertEqual(resp.status_code, 200)

    def test_api_list_and_detail_gated(self):
        appt = Appointment.objects.create(
            patient=make_patient("MRN-RO2"), facility=self.f1,
            start_datetime=next_weekday_slot(),
        )
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/api/clinic/appointments/").status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/clinic/appointments/{appt.pk}/").status_code, 403
        )
        self._enable_site()
        self.assertEqual(self.client.get("/api/clinic/appointments/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/clinic/appointments/{appt.pk}/").status_code, 200
        )

    def test_superuser_bypasses_gate(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get("/clinic/appointments/").status_code, 200)
        self.assertEqual(self.client.get("/api/clinic/appointments/").status_code, 200)

    # -- Layout nav visibility (Phase 4: clinic links gated by the rollout flag)
    def _nav_contains_clinic(self, user):
        self.client.force_login(user)
        resp = self.client.get("/worklist")
        self.assertEqual(resp.status_code, 200)
        # The context processor runs at render time; assert on its *computed*
        # value so a stray "Clinic" string elsewhere in the page can't create
        # a false positive.
        self.assertTrue(
            resp.context["clinic_nav"]["visible"],
            "clinic_nav context processor expected visible=True",
        )
        html = resp.content.decode()
        self.assertIn("bi-hospital", html)
        self.assertIn("Appointments", html)
        # Sanity: anonymous visitors never see the nav either.
        self.client.logout()
        anon = self.client.get("/worklist")
        if anon.status_code == 200:
            self.assertFalse(anon.context["clinic_nav"]["visible"])
        return True

    def test_nav_hides_clinic_links_for_disabled_site(self):
        # Staff whose only site is not rolled out must not see clinic links.
        self.assertFalse(self._nav_contains_clinic(self.staff))

    def test_nav_shows_clinic_links_once_site_live(self):
        self._enable_site()
        self.assertTrue(self._nav_contains_clinic(self.staff))

    def test_nav_visible_to_superuser_ops_bypass(self):
        self.assertTrue(self._nav_contains_clinic(self.superuser))

    def test_outbox_skips_disabled_facility(self):
        from clinic import outbox as outbox_mod

        ev = IntegrationEvent.objects.create(
            event_type="APPT_BOOKED", facility=self.f1,
            entity_type="Appointment", entity_id=uuid.uuid4(),
            payload={"a": 1}, status="PENDING",
        )
        delivered, dead = outbox_mod.deliver_pending()
        self.assertEqual((delivered, dead), (0, 0))
        ev.refresh_from_db()
        self.assertEqual(ev.status, "PENDING")
        self.assertEqual(ev.delivery_attempts, 0)  # skipped, not failed
        self._enable_site()
        delivered, dead = outbox_mod.deliver_pending()
        self.assertGreaterEqual(delivered, 1)
        ev.refresh_from_db()
        self.assertEqual(ev.status, "DELIVERED")


class PermissionMatrixTests(TestCase):
    """Phase 4 (Step 5.1): role x action matrix encoded as tests.

    Matrix (per section-E answer — receptionists may create encounters but
    cannot open clinical documentation flows):
      RECEPTIONIST : book/cancel appointments, check in, create encounter
      PROVIDER     : everything clinical (notes, vitals, signing)
      BILLER       : no clinical routes
      ADMIN/staff  : availability config, duplicate review
    """

    def setUp(self):
        from license.models import LicenseActivation

        LicenseActivation.objects.create(
            pk=1, expiry_date=date.today() + timedelta(days=365),
            signature="TESTSIG", max_orders=None,
        )
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.f2 = Facility.objects.create(name="Site B", dicom_ae_title="AE_B")
        # Site A live (one ADMIN assignment opens the whole facility).
        FacilityAssignment.objects.create(
            user=make_user("admin-a@clinic.test"), facility=self.f1,
            role_at_facility="ADMIN", start_date=date.today() - timedelta(days=1),
        )
        self.receptionist = make_user("recep@clinic.test", facility=self.f1)
        self.provider = make_user("dr@clinic.test")
        FacilityAssignment.objects.create(
            user=self.provider, facility=self.f1, role_at_facility="PROVIDER",
            start_date=date.today() - timedelta(days=1),
        )
        self.biller = make_user("biller@clinic.test")
        FacilityAssignment.objects.create(
            user=self.biller, facility=self.f1, role_at_facility="BILLER",
            start_date=date.today() - timedelta(days=1),
        )
        self.patient = make_patient("MRN-MX1")
        self.foreign_appt = Appointment.objects.create(
            patient=make_patient("MRN-MX2"), facility=self.f2,
            start_datetime=next_weekday_slot(),
        )
        self.enc = Encounter.objects.create(patient=self.patient, facility=self.f1)

    def _get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_receptionist_can_view_queue_and_book(self):
        self.assertEqual(
            self._get(self.receptionist, "/clinic/queue/").status_code, 200
        )
        self.assertEqual(
            self._get(self.receptionist, "/clinic/appointments/new/").status_code, 200
        )

    def test_receptionist_blocked_from_provider_only_routes(self):
        self.assertEqual(
            self._get(self.receptionist, "/clinic/availability/").status_code, 403
        )
        # section-E answer: receptionists MAY create encounters (registration
        # workflow), so the encounter form stays open to them.
        self.assertEqual(
            self._get(self.receptionist, "/clinic/encounters/new/").status_code, 200
        )

    def test_provider_can_view_lists_and_availability(self):
        # providers cover everything clinical + read access to ops views.
        self.assertEqual(
            self._get(self.provider, "/clinic/appointments/").status_code, 200
        )
        self.assertEqual(
            self._get(self.provider, "/clinic/availability/").status_code, 200
        )

    def test_biller_has_no_clinic_html_access(self):
        for url in ("/clinic/appointments/", "/clinic/encounters/", "/clinic/queue/"):
            self.assertEqual(self._get(self.biller, url).status_code, 403, url)

    def test_duplicate_review_is_admin_only(self):
        self.assertEqual(
            self._get(self.receptionist, "/clinic/patients/duplicates/").status_code, 403
        )
        self.assertEqual(
            self._get(self.provider, "/clinic/patients/duplicates/").status_code, 403
        )

    def test_cross_facility_appointment_invisible(self):
        # scoping regression: foreign-facility record 404s even at a live site
        self.assertEqual(
            self._get(self.provider, f"/clinic/appointments/{self.foreign_appt.pk}/")
            .status_code,
            404,
        )


class PatientMergeServiceTests(TestCase):
    """Phase 4 (Step 5.1): duplicate-identity merge service + tooling."""

    def setUp(self):
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.f2 = Facility.objects.create(name="Site B", dicom_ae_title="AE_B")
        self.actor = make_user("merge-admin@clinic.test", facility=self.f1)
        self.canonical = Patient.objects.create(
            mrn="MRN-CANON", first_name_en="Same", last_name_en="Person",
            dob=date(1985, 5, 5),
        )
        self.duplicate = Patient.objects.create(
            mrn="MRN-DUP", first_name_en="same", last_name_en="PERSON",
            dob=date(1985, 5, 5),
        )

    def _identifier(self, patient, facility, value, primary=True):
        return PatientFacilityIdentifier.objects.create(
            patient=patient, facility=facility, identifier_type="MRN",
            identifier=value, is_primary=primary,
        )

    def test_candidate_detection_conservative(self):
        from clinic import patient_matching

        other = Patient.objects.create(
            mrn="MRN-OTHER", first_name_en="Different", last_name_en="Person",
            dob=date(1985, 5, 5),
        )
        pairs = dict((d.pk, c.pk) for c, d in patient_matching.find_candidate_duplicates())
        self.assertEqual(pairs.get(self.duplicate.pk), self.canonical.pk)
        self.assertNotIn(other.pk, pairs)

    def test_merge_repoints_records_and_logs(self):
        from clinic import patient_matching

        self._identifier(self.canonical, self.f1, "A-1")
        self._identifier(self.duplicate, self.f2, "B-1")
        Encounter.objects.create(patient=self.duplicate, facility=self.f2)
        Appointment.objects.create(
            patient=self.duplicate, facility=self.f2,
            start_datetime=next_weekday_slot(),
        )

        summary = patient_matching.merge_patients(
            duplicate=self.duplicate, canonical=self.canonical, actor=self.actor
        )
        self.assertEqual(summary["repointed"]["clinic.Encounter"], 1)
        self.assertEqual(summary["repointed"]["clinic.Appointment"], 1)
        self.assertEqual(summary["identifiers_moved"], 1)
        self.duplicate.refresh_from_db()
        self.assertTrue(self.duplicate.is_deleted)
        self.assertIn("-MERGED-", self.duplicate.mrn)
        # identifiers now all on canonical
        ids = PatientFacilityIdentifier.objects.filter(patient=self.canonical)
        self.assertEqual(ids.count(), 2)
        # append-only merge log + audit row written
        log = PatientMergeLog.objects.get(duplicate=self.duplicate)
        self.assertEqual(log.canonical_id, self.canonical.pk)
        self.assertEqual(log.actor_id, self.actor.pk)
        self.assertTrue(
            AuditLog.objects.filter(
                action="CLINIC_PATIENT_MERGE", entity_id=str(self.duplicate.pk)
            ).exists()
        )

    def test_merge_log_is_append_only(self):
        from clinic import patient_matching

        patient_matching.merge_patients(
            duplicate=self.duplicate, canonical=self.canonical, actor=self.actor
        )
        log = PatientMergeLog.objects.get()
        with self.assertRaises(ValidationError):
            log.summary = {"tampered": True}
            log.save()
        with self.assertRaises(ValidationError):
            log.delete()

    def test_self_merge_rejected(self):
        from clinic import patient_matching

        with self.assertRaises(ValidationError):
            patient_matching.merge_patients(
                duplicate=self.canonical, canonical=self.canonical, actor=self.actor
            )

    def test_identifier_collision_stays_detached(self):
        from clinic import patient_matching

        # Collision is on the per-site unique key (facility, type, value);
        # canonical holds the same identifier at a *different* site so the
        # duplicate's row can't move to f1 without violating it.
        self._identifier(self.canonical, self.f2, "SAME-VALUE")
        self._identifier(self.duplicate, self.f1, "SAME-VALUE", primary=False)
        summary = patient_matching.merge_patients(
            duplicate=self.duplicate, canonical=self.canonical, actor=self.actor
        )
        self.assertEqual(summary["identifiers_moved"], 0)
        self.assertEqual(
            PatientFacilityIdentifier.objects.get(identifier="SAME-VALUE").patient_id,
            self.duplicate.pk,
        )


class OrdersWorklistScopingTests(TestCase):
    """Phase 4 (Step 5.1 sweep): legacy RIS order views share the one
    facility-scoping layer; unaffiliated accounts keep global visibility."""

    def setUp(self):
        from license.models import LicenseActivation

        LicenseActivation.objects.create(
            pk=1, expiry_date=date.today() + timedelta(days=365),
            signature="TESTSIG", max_orders=None,
        )
        from core.models import Modality

        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.f2 = Facility.objects.create(name="Site B", dicom_ae_title="AE_B")
        self.mod = Modality.objects.create(code="CT", name="CT")
        self.patient = make_patient("MRN-ORD1")
        self.affiliated = make_user("risc@clinic.test", facility=self.f1)
        self.legacy = make_user("global-ris@clinic.test")  # no facility
        self.o1 = ExamOrder.objects.create(
            patient=self.patient, facility=self.f1, modality=self.mod,
            accession_number="ACC-A1", procedure_code="C1", procedure_name_en="CT head",
        )
        self.o2 = ExamOrder.objects.create(
            patient=self.patient, facility=self.f2, modality=self.mod,
            accession_number="ACC-B1", procedure_code="C2", procedure_name_en="CT chest",
        )
        self.o3 = ExamOrder.objects.create(
            patient=self.patient, facility=None, modality=self.mod,
            accession_number="ACC-N1", procedure_code="C3", procedure_name_en="Unassigned",
        )

    def _get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_affiliated_user_sees_own_site_and_unassigned(self):
        resp = self._get(self.affiliated, "/orders/")
        self.assertEqual(resp.status_code, 200)
        ids = {o.pk for o in resp.context["orders"]}
        self.assertEqual(ids, {self.o1.pk, self.o3.pk})

    def test_legacy_unaffiliated_user_sees_everything(self):
        resp = self._get(self.legacy, "/orders/")
        ids = {o.pk for o in resp.context["orders"]}
        self.assertEqual(ids, {self.o1.pk, self.o2.pk, self.o3.pk})

    def test_cross_facility_order_detail_404(self):
        self.assertEqual(
            self._get(self.affiliated, f"/orders/{self.o2.pk}/").status_code, 404
        )
        self.assertEqual(
            self._get(self.affiliated, f"/orders/{self.o1.pk}/").status_code, 200
        )
