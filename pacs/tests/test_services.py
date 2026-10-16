"""Unit tests for PACS sync services (PACS plan Task 6.1, Phase 2/3 scope).

Synthetic data only — no PHI, no DICOM files in Git.
"""

from datetime import date

from django.test import TestCase

from core.models import Device, Facility, Modality
from orders.models import ExamOrder
from patients.models import Patient
from pacs.dicom_uid import is_valid_dicom_uid
from pacs.models import PACSStudy, StudyStatus, SyncEvent
from pacs.orthanc_client import OrthancAPIError, OrthancUnavailable
from pacs.services import (
    MatchOutcome,
    apply_matching_policy,
    process_changes,
    replay_all_studies,
    resolve_parent_study,
    sync_study_from_archive,
)

STUDY_UID = "1.2.840.113619.2.55.3.12345.1"
SERIES_UID = "1.2.840.113619.2.55.3.12345.1.1"


class FakeOrthancClient:
    """Scriptable stand-in for the archive REST adapter."""

    def __init__(self, studies=None, series=None, changes=None, study_list=None):
        self.studies = studies or {}          # orthanc_id -> study dict
        self.series = series or {}            # orthanc_id -> series dict
        self.changes = changes or []
        self.study_list = study_list or list(self.studies.keys())
        self.calls = []

    def get_study(self, orthanc_id, expand=False):
        self.calls.append(("get_study", orthanc_id))
        return self.studies.get(orthanc_id)

    def _request(self, path, **kwargs):
        if path.startswith("/series/"):
            sid = path.split("/")[2]
            return self.series.get(sid)
        if path == "/studies":
            return self.study_list
        if path.startswith("/instances/") or path.startswith("/series/"):
            return None
        raise AssertionError(f"unexpected request {path}")

    def get_changes(self, since=None):
        out = [c for c in self.changes if since is None or c["Index"] > since]
        last = max((c["Index"] for c in self.changes), default=None)
        return out, last

    def resolve_parent_study(self, orthanc_id):
        """Test hook mirroring the real parent-resolution REST lookups."""
        return None


def make_orthanc_study(
    orthanc_id="study-1",
    uid=STUDY_UID,
    accession="",
    patient_id="",
    modality_series=("CT",),
    instances=2,
    study_date="20261001",
    study_time="120000",
):
    series_ids = [f"series-{orthanc_id}-{i}" for i in range(len(modality_series))]
    return orthanc_id, {
        "ID": orthanc_id,
        "MainDicomTags": {
            "StudyInstanceUID": uid,
            "AccessionNumber": accession,
            "PatientID": patient_id,
            "StudyDate": study_date,
            "StudyTime": study_time,
            "StudyDescription": "TEST STUDY",
            "PatientName": "TEST^PATIENT",
            "ReferringPhysicianName": "DOC^REFERRING",
        },
        "Series": series_ids,
    }, {
        sid: {"ID": sid, "Instances": [f"inst-{sid}-{n}" for n in range(instances)]}
        for sid in series_ids
    }


class UidValidationTests(TestCase):
    def test_valid_uids(self):
        for uid in ("1.2.840.10008.5.1.4.1.1.2", "1", "1.2.3.4.5"):
            self.assertTrue(is_valid_dicom_uid(uid), uid)

    def test_invalid_uids(self):
        bad = [
            "",
            None,
            "abc",
            "1.2.084",           # leading zero component
            "1..2",              # empty component
            ".1.2",
            "1.2.",
            "1 2.3",             # internal space
            "1." + "2" * 70,     # too long (>64)
            "not.a.uid!",
        ]
        for uid in bad:
            self.assertFalse(is_valid_dicom_uid(uid), repr(uid))


class FixtureMixin:
    def setUpFixtures(self):
        self.facility = Facility.objects.create(
            name="Fac A", dicom_ae_title="FAC_A_PACS_AE"
        )
        self.other_facility = Facility.objects.create(
            name="Fac B", dicom_ae_title="FAC_B_PACS_AE"
        )
        self.modality = Modality.objects.create(code="CT")
        self.device = Device.objects.create(
            facility=self.facility,
            modality=self.modality,
            name="CT-1",
            dicom_ae_title="MODALITY_CT_1",
            dicom_host="10.0.0.10",
        )
        self.patient = Patient.objects.create(
            mrn="MRN001",
            first_name_en="Test",
            last_name_en="Patient",
            dob=date(1980, 1, 1),
            gender="M",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient,
            facility=self.facility,
            accession_number="ACC0001",
            modality=self.modality,
            procedure_code="CT_HEAD",
            procedure_name_en="CT Head",
        )


class SyncStudyTests(FixtureMixin, TestCase):
    def setUp(self):
        self.setUpFixtures()

    def test_new_study_sync_and_indexing(self):
        oid, study, series = make_orthanc_study(accession="ACC0001", patient_id="MRN001")
        client = FakeOrthancClient(studies={oid: study}, series=series)
        obj = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertIsNotNone(obj)
        self.assertEqual(obj.study_instance_uid, STUDY_UID)
        self.assertEqual(obj.series_count, 1)
        self.assertEqual(obj.instance_count, 2)
        self.assertEqual(obj.facility_id, self.facility.id)
        self.assertEqual(obj.sender_device_id, self.device.id)
        # Rule 2 match: accession + MRN + facility → linked & available.
        self.assertEqual(obj.matched_order_id, self.order.pk)
        self.assertEqual(obj.status, StudyStatus.AVAILABLE)
        # Task 3.2: UID written back to order because field was empty.
        self.order.refresh_from_db()
        self.assertEqual(self.order.dicom_study_instance_uid, STUDY_UID)

    def test_duplicate_retransmission_is_idempotent(self):
        oid, study, series = make_orthanc_study(accession="ACC0001", patient_id="MRN001")
        client = FakeOrthancClient(studies={oid: study}, series=series)
        first = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        second = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertEqual(PACSStudy.objects.count(), 1)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.status, StudyStatus.AVAILABLE)
        self.assertEqual(second.instance_count, 2)

    def test_uid_collision_with_different_content_flags_conflict(self):
        oid, study, series = make_orthanc_study(accession="ACC0001", patient_id="MRN001")
        client = FakeOrthancClient(studies={oid: study}, series=series)
        sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        # Same Study UID arrives with a different PatientID.
        study["MainDicomTags"]["PatientID"] = "MRN999"
        second = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertEqual(second.status, StudyStatus.INTEGRITY_CONFLICT)
        self.assertIn("PatientID", second.status_reason)
        # The previously established link must not be silently destroyed.
        self.assertEqual(second.matched_order_id, self.order.pk)

    def test_unknown_sender_lands_in_reconciliation(self):
        oid, study, series = make_orthanc_study(accession="ACC0001", patient_id="MRN001")
        client = FakeOrthancClient(studies={oid: study}, series=series)
        obj = sync_study_from_archive(client, oid, calling_ae_title="ROGUE_AE")
        self.assertIsNone(obj.facility_id)
        self.assertEqual(obj.status, StudyStatus.RECONCILIATION_REQUIRED)
        self.assertIn("unknown sender", obj.status_reason)

    def test_no_match_goes_to_reconciliation_not_linked(self):
        oid, study, series = make_orthanc_study(
            accession="UNKNOWN-ACC", patient_id="UNKNOWN-MRN"
        )
        client = FakeOrthancClient(studies={oid: study}, series=series)
        obj = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertIsNone(obj.matched_order_id)
        self.assertEqual(obj.status, StudyStatus.RECONCILIATION_REQUIRED)

    def test_exact_uid_rule1_beats_accession(self):
        self.order.dicom_study_instance_uid = STUDY_UID
        self.order.save()
        oid, study, series = make_orthanc_study()  # no accession/patient id
        client = FakeOrthancClient(studies={oid: study}, series=series)
        obj = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertEqual(obj.matched_order_id, self.order.pk)
        self.assertEqual(obj.status, StudyStatus.AVAILABLE)

    def test_existing_different_order_uid_never_overwritten(self):
        self.order.dicom_study_instance_uid = "1.2.840.999.1"
        self.order.save()
        oid, study, series = make_orthanc_study(accession="ACC0001", patient_id="MRN001")
        client = FakeOrthancClient(studies={oid: study}, series=series)
        obj = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertIsNone(obj.matched_order_id)
        self.assertEqual(obj.status, StudyStatus.RECONCILIATION_REQUIRED)
        self.assertIn("different Study UID", obj.status_reason)
        self.order.refresh_from_db()
        self.assertEqual(self.order.dicom_study_instance_uid, "1.2.840.999.1")

    def test_invalid_study_uid_recorded_as_failed_event(self):
        oid, study, series = make_orthanc_study(uid="NOT-A-VALID-UID")
        client = FakeOrthancClient(studies={oid: study}, series=series)
        result = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertIsNone(result)
        self.assertEqual(PACSStudy.objects.count(), 0)
        events = SyncEvent.objects.filter(error_category="invalid_study_uid")
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().outcome, SyncEvent.Outcome.FAILED)
        # Repeated sighting does not duplicate the marker row.
        sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertEqual(SyncEvent.objects.filter(error_category="invalid_study_uid").count(), 1)

    def test_facility_context_taken_from_sender_not_tags(self):
        """Incoming tags cannot move ownership: same AE always maps same facility."""
        oid, study, series = make_orthanc_study(accession="ACC0001", patient_id="MRN001")
        client = FakeOrthancClient(studies={oid: study}, series=series)
        obj = sync_study_from_archive(client, oid, calling_ae_title="MODALITY_CT_1")
        self.assertEqual(obj.facility_id, self.facility.id)
        # Even if DICOM tags were manipulated, facility stays sender-derived;
        # verified by re-sync from a device of another facility → conflict.
        dev_b = Device.objects.create(
            facility=self.other_facility,
            modality=self.modality,
            name="CT-2",
            dicom_ae_title="MODALITY_CT_2",
            dicom_host="10.0.0.11",
        )
        obj2 = sync_study_from_archive(client, oid, calling_ae_title=dev_b.dicom_ae_title)
        self.assertEqual(obj2.facility_id, self.facility.id)  # unchanged owner
        self.assertEqual(obj2.status, StudyStatus.INTEGRITY_CONFLICT)
        self.assertIn("cross-facility", obj2.status_reason)


class MatchingPolicyTests(FixtureMixin, TestCase):
    def setUp(self):
        self.setUpFixtures()

    def _study(self, **kw):
        defaults = dict(
            study_instance_uid=STUDY_UID,
            accession_number="",
            patient_id_as_received="",
            facility=self.facility,
        )
        defaults.update(kw)
        return PACSStudy(**defaults)

    def test_never_matches_on_name_or_description(self):
        self.order.patient.first_name_en = "TEST"
        self.order.patient.save()
        study = self._study(patient_name_as_received="TEST^PATIENT",
                            study_description="CT HEAD")
        outcome, order, reason = apply_matching_policy(study)
        self.assertEqual(outcome, MatchOutcome.UNMATCHED)
        self.assertIsNone(order)

    def test_ambiguous_accession_mrn_multiple_orders_conflicts(self):
        # Simulate legacy duplicate rows (DB unique constraint normally
        # prevents this) by inserting the second order via raw SQL bypass.
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO orders_examorder ("
                "id, patient_id, facility_id, accession_number, referring_physician,"
                " modality_id, procedure_code, procedure_name_en, procedure_name_ar,"
                " priority, clinical_indication, laterality, body_part,"
                " contrast_required, status, scheduled_datetime, duration_minutes,"
                " room_station_id, dicom_study_instance_uid, hl7_message_control_id,"
                " billing_status, is_deleted, deleted_at, created_by_id,"
                " created_at, updated_at, appointment_id)"
                " SELECT id, patient_id, facility_id, accession_number,"
                " referring_physician, modality_id, procedure_code, procedure_name_en,"
                " procedure_name_ar, priority, clinical_indication, laterality,"
                " body_part, contrast_required, status, scheduled_datetime,"
                " duration_minutes, room_station_id, dicom_study_instance_uid,"
                " hl7_message_control_id, billing_status, is_deleted, deleted_at,"
                " created_by_id, created_at, updated_at, appointment_id "
                "FROM orders_examorder WHERE accession_number='ACC0001'"
            )
        study = self._study(accession_number="ACC0001", patient_id_as_received="MRN001")
        outcome, _, reason = apply_matching_policy(study)
        self.assertEqual(outcome, MatchOutcome.CONFLICT)
        self.assertIn("candidate orders", reason)


class ChangesFeedTests(FixtureMixin, TestCase):
    def setUp(self):
        self.setUpFixtures()
        self.oid, self.study, self.series = make_orthanc_study(
            accession="ACC0001", patient_id="MRN001"
        )

    def test_process_changes_durable_cursor_and_idempotency(self):
        changes = [
            {"Index": 1, "Path": f"instances/inst-1", "Type": "NewInstance",
             "SourceAETitle": "MODALITY_CT_1"},
        ]
        client = FakeOrthancClient(
            studies={self.oid: self.study},
            series=self.series,
            changes=changes,
        )
        # instance change → parent resolution needs /instances lookup; our
        # fake returns None → event recorded FAILED (visible, not silent).
        counters = process_changes(client=client)
        self.assertEqual(counters["failed"], 1)
        ev = SyncEvent.objects.get(change=1)
        self.assertEqual(ev.outcome, SyncEvent.Outcome.FAILED)

        # Direct study-level change succeeds and is durable.
        changes2 = [
            {"Index": 2, "Path": f"studies/{self.oid}", "Type": "NewResource",
             "SourceAETitle": "MODALITY_CT_1"},
        ]
        client2 = FakeOrthancClient(
            studies={self.oid: self.study}, series=self.series, changes=changes2
        )
        counters = process_changes(client=client2)
        self.assertEqual(counters["processed"], 1)
        self.assertEqual(PACSStudy.objects.count(), 1)
        # Replay of the same feed ignores already-processed indices.
        counters = process_changes(client=client2)
        self.assertEqual(counters["ignored"], 1)
        self.assertEqual(PACSStudy.objects.count(), 1)

    def test_archive_outage_raises_and_leaves_pending_event(self):
        class DownClient(FakeOrthancClient):
            def get_study(self, orthanc_id, expand=False):
                raise OrthancUnavailable("down")

            def get_changes(self, since=None):
                return [
                    {"Index": 5, "Path": f"studies/{self.oid}", "Type": "NewResource"}
                ], 5

        client = DownClient()
        with self.assertRaises(OrthancUnavailable):
            process_changes(client=client)
        ev = SyncEvent.objects.get(change=5)
        self.assertEqual(ev.outcome, SyncEvent.Outcome.PENDING)
        self.assertEqual(ev.error_category, "archive_unavailable")
        # Cursor did not advance past the pending event's index... it is
        # stored, so next poll resumes after it; the mirror has no row yet.
        self.assertEqual(PACSStudy.objects.count(), 0)

    def test_restart_does_not_lose_processed_state(self):
        SyncEvent.objects.create(
            change=10, path="studies/x", resource_type="Study",
            outcome=SyncEvent.Outcome.PROCESSED,
        )
        client = FakeOrthancClient(
            studies={self.oid: self.study},
            series=self.series,
            changes=[{"Index": 10, "Path": f"studies/{self.oid}", "Type": "NewResource"}],
        )
        counters = process_changes(client=client)
        self.assertEqual(counters["ignored"], 1)  # resume from cursor, no dup work

    def test_replay_rebuilds_mirror(self):
        client = FakeOrthancClient(
            studies={self.oid: self.study}, series=self.series
        )
        result = replay_all_studies(client=client)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(PACSStudy.objects.filter(study_instance_uid=STUDY_UID).count(), 1)
        # Re-run is idempotent.
        result = replay_all_studies(client=client)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(PACSStudy.objects.count(), 1)
