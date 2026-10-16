"""Reconciliation queue service tests (PACS plan Phase 3, Tasks 3.3–3.4).

Synthetic data only — no PHI. Covers: role gating, facility scoping
(URL-ID manipulation), audited before/after state, conflict refusal,
and the non-destructive resolution paths.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from audit.models import AuditLog
from clinic.models import FacilityAssignment
from core.models import Device, Facility, Modality
from orders.models import ExamOrder
from patients.models import Patient
from pacs.models import PACSStudy, StudyStatus
from pacs.reconciliation import (
    can_reconcile,
    manual_link,
    manual_unlink,
    mark_incorrectly_received,
    move_facility,
    preview_link,
    reconciliation_queue,
    rematch,
    scoped_studies,
)

STUDY_UID = "1.2.840.113619.2.55.3.77777.1"
OTHER_UID = "1.2.840.113619.2.55.3.88888.1"

User = get_user_model()


class ReconciliationFixtureMixin:
    def setUpFixtures(self):
        self.facility_a = Facility.objects.create(name="Fac A")
        self.facility_b = Facility.objects.create(name="Fac B")
        self.modality = Modality.objects.create(code="CT")
        self.device = Device.objects.create(
            facility=self.facility_a,
            modality=self.modality,
            name="CT-1",
            dicom_ae_title="REC_CT_1",
        )
        self.patient = Patient.objects.create(
            mrn="MRN900",
            first_name_en="Recon",
            last_name_en="Patient",
            dob="1980-01-01",
            gender="M",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient,
            facility=self.facility_a,
            accession_number="ACC900",
            modality=self.modality,
            procedure_code="CT_HEAD",
            procedure_name_en="CT Head",
        )
        self.study = PACSStudy.objects.create(
            study_instance_uid=STUDY_UID,
            facility=self.facility_a,
            sender_device=self.device,
            accession_number="ACC900",
            patient_id_as_received="MRN900",
            status=StudyStatus.RECONCILIATION_REQUIRED,
            status_reason="manual review needed",
        )
        self.provider = User.objects.create_user(
            username="prov_a", email="prov@a.test", password="x",
            facility=self.facility_a,
        )
        FacilityAssignment.objects.create(
            user=self.provider,
            facility=self.facility_a,
            role_at_facility="PROVIDER",
            start_date="2026-01-01",
        )
        self.tech = User.objects.create_user(
            username="tech_a", email="tech@a.test", password="x",
            facility=self.facility_a,
        )
        FacilityAssignment.objects.create(
            user=self.tech,
            facility=self.facility_a,
            role_at_facility="TECHNICIAN",
            start_date="2026-01-01",
        )
        self.provider_b = User.objects.create_user(
            username="prov_b", email="prov@b.test", password="x",
            facility=self.facility_b,
        )
        FacilityAssignment.objects.create(
            user=self.provider_b,
            facility=self.facility_b,
            role_at_facility="PROVIDER",
            start_date="2026-01-01",
        )
        self.superuser = User.objects.create_superuser(
            username="recon_root", email="root@a.test", password="x"
        )


class QueueScopingTests(ReconciliationFixtureMixin, TestCase):
    def setUp(self):
        self.setUpFixtures()

    def test_facility_a_provider_sees_own_study_only(self):
        ids = [s.pk for s in reconciliation_queue(self.provider)]
        self.assertIn(self.study.pk, ids)

    def test_cross_facility_user_cannot_see_or_act_by_url_id(self):
        # Provider at Fac B cannot list the study...
        ids = [s.pk for s in reconciliation_queue(self.provider_b)]
        self.assertNotIn(self.study.pk, ids)
        # ...and acting by guessed study ID is refused identically to a
        # nonexistent row (no existence leak).
        with self.assertRaises(PermissionDenied):
            manual_unlink(self.provider_b, self.study.pk, reason="probe")

    def test_technician_can_view_but_not_act(self):
        ids = [s.pk for s in reconciliation_queue(self.tech)]
        self.assertIn(self.study.pk, ids)
        self.assertFalse(can_reconcile(self.tech))
        with self.assertRaises(PermissionDenied):
            mark_incorrectly_received(self.tech, self.study.pk, reason="nope")

    def test_unassigned_facility_studies_hidden_from_regular_users(self):
        orphan = PACSStudy.objects.create(
            study_instance_uid=OTHER_UID,
            status=StudyStatus.RECONCILIATION_REQUIRED,
        )
        self.assertNotIn(orphan.pk, [s.pk for s in reconciliation_queue(self.provider)])
        self.assertIn(orphan.pk, [s.pk for s in reconciliation_queue(self.superuser)])


class LinkActionTests(ReconciliationFixtureMixin, TestCase):
    def setUp(self):
        self.setUpFixtures()

    def test_preview_link_shows_dicom_vs_ris_differences(self):
        self.study.accession_number = "ACCXXX"
        self.study.patient_id_as_received = "MRNOVER"
        self.study.save()
        diffs = preview_link(self.study, self.order)
        fields = {d["field"] for d in diffs}
        self.assertIn("accession_number", fields)
        self.assertIn("patient_id/MRN", fields)

    def test_manual_link_sets_order_uid_and_audits(self):
        manual_link(self.provider, self.study.pk, self.order.pk, reason="verified wristband")
        self.study.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.study.matched_order_id, self.order.pk)
        self.assertEqual(self.study.status, StudyStatus.AVAILABLE)
        self.assertEqual(self.order.dicom_study_instance_uid, STUDY_UID)
        entry = AuditLog.objects.filter(
            entity_type="PACSStudy", action="pacs.manual_link"
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(str(entry.user_id), str(self.provider.pk))
        self.assertIn("verified wristband", str(entry.new_values))
        self.assertIn("matched_order", entry.old_values)

    def test_manual_link_refuses_overwrite_different_order_uid(self):
        ExamOrder.objects.filter(pk=self.order.pk).update(
            dicom_study_instance_uid=OTHER_UID
        )
        with self.assertRaises(ValueError):
            manual_link(self.provider, self.study.pk, self.order.pk, reason="x")
        self.study.refresh_from_db()
        self.assertIsNone(self.study.matched_order_id)

    def test_manual_link_refuses_cross_facility_order(self):
        order_b = ExamOrder.objects.create(
            patient=self.patient,
            facility=self.facility_b,
            accession_number="ACC901",
            modality=self.modality,
            procedure_code="CT_CHEST",
            procedure_name_en="CT Chest",
        )
        with self.assertRaises(PermissionDenied):
            # provider of A must not even resolve an order at B by guessed id
            manual_link(self.provider, self.study.pk, order_b.pk, reason="x")

    def test_unlink_clears_link_and_order_uid_with_audit(self):
        manual_link(self.provider, self.study.pk, self.order.pk, reason="link first")
        manual_unlink(self.provider, self.study.pk, reason="wrong patient")
        self.study.refresh_from_db()
        self.order.refresh_from_db()
        self.assertIsNone(self.study.matched_order_id)
        self.assertEqual(self.study.status, StudyStatus.RECONCILIATION_REQUIRED)
        self.assertEqual(self.order.dicom_study_instance_uid, "")
        self.assertTrue(
            AuditLog.objects.filter(action="pacs.manual_unlink").exists()
        )

    def test_mark_incorrectly_received_is_non_destructive(self):
        manual_link(self.provider, self.study.pk, self.order.pk, reason="link first")
        mark_incorrectly_received(
            self.provider, self.study.pk, reason="wrong site send"
        )
        self.study.refresh_from_db()
        # Study row still exists (archive untouched); link removed.
        self.assertTrue(PACSStudy.objects.filter(pk=self.study.pk).exists())
        self.assertIsNone(self.study.matched_order_id)
        self.assertIn("incorrectly received", self.study.status_reason)

    def test_move_facility_requires_access_to_both_ends(self):
        # Provider A cannot move to B (not assigned at B).
        with self.assertRaises(PermissionDenied):
            move_facility(self.provider, self.study.pk, self.facility_b.pk, "x")
        # Superuser may, and both facilities appear in the audit trail.
        move_facility(
            self.superuser, self.study.pk, self.facility_b.pk, reason="sent to wrong site"
        )
        self.study.refresh_from_db()
        self.assertEqual(self.study.facility_id, self.facility_b.pk)
        entry = AuditLog.objects.filter(action="pacs.move_facility").first()
        self.assertEqual(entry.old_values["facility"], str(self.facility_a.pk))
        self.assertEqual(entry.new_values["facility"], str(self.facility_b.pk))

    def test_rematch_after_correction_links_automatically(self):
        outcome = rematch(self.provider, self.study.pk)
        # Deterministic rule 2 applies now (accession+MRN+facility unique).
        outcome.refresh_from_db()
        self.assertEqual(outcome.status, StudyStatus.AVAILABLE)
        self.assertEqual(outcome.matched_order_id, self.order.pk)
        self.assertTrue(AuditLog.objects.filter(action="pacs.rematch").exists())
