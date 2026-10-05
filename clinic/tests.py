"""Clinic module tests — encodes plan Verification items 1-5.

Phase 0 covers: facility-scoped access with shared patient identity (1),
cross-module schema links for encounter billing & appointments (4, structural),
migrations/checks (5). Items 2-3 (conflict engine transitions, note signing)
land with Phases 1-2; the corresponding test classes are stubbed below.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog
from billing.models import PatientAccount, ServiceLine
from clinic.models import (
    Appointment,
    Encounter,
    FacilityAssignment,
    PatientFacilityIdentifier,
)
from clinic.permissions import accessible_facility_ids, has_facility_access
from core.mixins import FacilityScopedModel
from core.models import Facility
from patients.models import Patient
from users.models import User


class TestUser(FacilityScopedModel):
    """Concrete subclass of the abstract mixin for scoping tests only."""

    class Meta:
        app_label = "clinic"


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
            TestUser.objects.create(facility=f, name=str(f))

    def test_home_facility_only(self):
        rows = TestUser.objects.for_user(self.user)
        self.assertEqual(list(rows), [TestUser.objects.filter(facility=self.f1).first()])

    def test_assignment_grants_second_site(self):
        FacilityAssignment.objects.create(
            user=self.user, facility=self.f2, role_at_facility="RECEPTIONIST",
            start_date=date.today(),
        )
        ids = accessible_facility_ids(self.user)
        self.assertEqual(ids, {self.f1.pk, self.f2.pk})
        self.assertTrue(has_facility_access(self.user, self.f2.pk))
        self.assertFalse(has_facility_access(self.user, self.f3.pk))
        self.assertEqual(TestUser.objects.for_user(self.user).count(), 2)

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
        self.assertEqual(TestUser.objects.for_user(root).count(), 3)

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
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServiceLine.objects.create(
                    exam_order=self._make_exam_order(), encounter=self.encounter,
                    **self._line_kwargs(),
                )

    def test_neither_source_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
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


class SchedulingTransitionTests(TestCase):
    """Verification item 2: state machine transitions (full conflict engine in Phase 1)."""

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


class SignedNoteImmutabilityTests(TestCase):
    """Verification item 3: placeholder — EncounterNote lands in Phase 2
    (append-only versions + hash chain + dual audit writes)."""
