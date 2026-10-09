"""Clinic module tests — encodes plan Verification items 1-5.

Phase 0 covers: facility-scoped access with shared patient identity (1),
cross-module schema links for encounter billing & appointments (4, structural),
migrations/checks (5). Items 2-3 (conflict engine transitions, note signing)
land with Phases 1-2; the corresponding test classes are stubbed below.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

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
    ProviderAvailability,
    RoomBooking,
    Vitals,
)
from clinic.permissions import accessible_facility_ids, has_facility_access
from core.models import Facility
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
        return EncounterNote.objects.create(encounter=self.enc, author=self.author, body=body)

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
        self.assertEqual(line.total_price, Decimal("50.00"))
        self.assertEqual(PatientAccount.objects.get(pk=self.account.pk).patient_id,
                         self.patient.pk)

    def test_exam_order_source_still_works(self):
        """RIS billing path untouched by the encounter link (addendum A.1)."""
        from orders.models import ExamOrder, Modality as _M  # noqa: F401

        from core.models import Modality

        mod = Modality.objects.create(code="CT", name="CT")
        order = ExamOrder.objects.create(
            patient=self.patient, facility=self.f1, accession_number="ACC-BL-1",
            modality=mod, procedure_code="CT-01", procedure_name_en="Head CT",
        )
        line = ServiceLine.objects.create(
            account=self.account, exam_order=order, code="CT-01",
            name="Head CT", unit_price=Decimal("200.00"), quantity=1,
        )
        self.assertEqual(line.total_price, Decimal("200.00"))


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
        from clinic import scheduling

        self.scheduling = scheduling
        self.f1 = Facility.objects.create(name="Site A", dicom_ae_title="AE_A")
        self.f2 = Facility.objects.create(name="Site B", dicom_ae_title="AE_B")
        self.patient = make_patient("MRN-API1")
        self.provider = make_user("api-dr@clinic.test")
        self.user = make_user("api-user@clinic.test", facility=self.f1)
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
        ids = [r["id"] for r in resp.json()]
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
