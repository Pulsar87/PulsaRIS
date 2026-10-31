from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase
from django.urls import reverse

from core.models import Facility, Modality
from orders.models import ExamOrder
from patients.models import Patient
from reports.models import Report
from users.models import User


def _make_vital_message(mrn, pulse_rate=72.0, spo2=98.0):
    from integrations.hl7.models import HL7VitalMessage, MessageStatus

    msg = HL7VitalMessage.objects.create(
        received_at=datetime(2026, 10, 1, 12, 0, tzinfo=dt_timezone.utc),
        status=MessageStatus.ACCEPTED,
        raw_hl7="MSH|^~\\&|EDAN|LAB|RIS|CLINIC|||ORU^R01|ctrl|T|2.5",
        parsed_json={
            "patient": {"patient_id": mrn, "names": []},
            "orders": [
                {
                    "set_id": "1",
                    "results": [
                        {
                            "observation": {"identifier": "PULSE"},
                            "value": str(pulse_rate),
                            "units": {"text": "bpm"},
                        },
                        {
                            "observation": {"identifier": "SPO2"},
                            "value": str(spo2),
                            "units": {"text": "%"},
                        },
                    ],
                }
            ],
        },
    )
    msg.apply_vitals()
    msg.save()
    return msg


class PatientAndReportAccessTests(TestCase):
    def setUp(self):
        self.facility = Facility.objects.create(name="Site A", dicom_ae_title="AE_SITE_A")
        self.modality = Modality.objects.create(code="CT", name="CT")
        self.user = User.objects.create_user(
            username="radiologist",
            email="radiologist@example.com",
            password="secret123",
            facility=self.facility,
            is_staff=True,
        )
        self.patient = Patient.objects.create(
            mrn="MRN-100",
            first_name_en="Alice",
            last_name_en="Example",
            dob=date(1980, 1, 1),
            gender="F",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient,
            facility=self.facility,
            accession_number="ACC-100",
            modality=self.modality,
            procedure_code="CT_HEAD",
            procedure_name_en="CT Head",
            priority=ExamOrder.Priority.ROUTINE,
            status=ExamOrder.Status.REGISTERED,
        )
        self.report = Report.objects.create(
            order=self.order,
            radiologist=self.user,
            status=Report.Status.DRAFT,
            findings_en="Initial findings",
        )

    def test_anonymous_views_redirect_to_login(self):
        self.assertEqual(self.client.get(reverse("patients:patient_list")).status_code, 302)
        self.assertEqual(self.client.get(reverse("reports:report_list")).status_code, 302)

    def test_user_without_facility_access_is_denied(self):
        no_facility_user = User.objects.create_user(
            username="noaccess",
            email="noaccess@example.com",
            password="secret123",
            facility=None,
        )
        self.client.force_login(no_facility_user)

        self.assertEqual(self.client.get(reverse("patients:patient_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reports:report_list")).status_code, 403)

    def test_staff_with_facility_can_view_their_reports(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("reports:report_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Initial findings")

    def test_cross_facility_patient_detail_is_not_visible(self):
        other_facility = Facility.objects.create(name="Site B", dicom_ae_title="AE_SITE_B")
        other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="secure-pass-123",
            facility=other_facility,
            is_staff=True,
        )
        other_patient = Patient.objects.create(
            mrn="MRN-200",
            first_name_en="Bob",
            last_name_en="Other",
            dob=date(1975, 5, 5),
            gender="M",
        )
        ExamOrder.objects.create(
            patient=other_patient,
            facility=other_facility,
            accession_number="ACC-200",
            modality=self.modality,
            procedure_code="CT_HEAD",
            procedure_name_en="CT Head",
            priority=ExamOrder.Priority.ROUTINE,
            status=ExamOrder.Status.REGISTERED,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("patients:patient_detail", args=[other_patient.pk]))
        self.assertEqual(response.status_code, 404)

        self.client.force_login(other_user)
        response = self.client.get(reverse("patients:patient_detail", args=[self.patient.pk]))
        self.assertEqual(response.status_code, 404)

class PatientHl7VitalsTests(TestCase):
    """HL7 vitals must be available per patient, linked from patient details."""

    def setUp(self):
        self.facility = Facility.objects.create(name="Site A", dicom_ae_title="AE_SITE_A")
        self.user = User.objects.create_user(
            username="nurse",
            email="nurse@example.com",
            password="secret123",
            facility=self.facility,
            is_staff=True,
        )
        self.patient_a = Patient.objects.create(
            mrn="MRN-100",
            first_name_en="Alice",
            last_name_en="Example",
            dob=date(1980, 1, 1),
            gender="F",
        )
        self.patient_b = Patient.objects.create(
            mrn="MRN-200",
            first_name_en="Bob",
            last_name_en="Other",
            dob=date(1975, 5, 5),
            gender="M",
        )
        # Anchor both patients to the facility so they are visible.
        modality = Modality.objects.create(code="CT", name="CT")
        for patient, accession in ((self.patient_a, "ACC-100"), (self.patient_b, "ACC-200")):
            ExamOrder.objects.create(
                patient=patient,
                facility=self.facility,
                accession_number=accession,
                modality=modality,
                procedure_code="CT_HEAD",
                procedure_name_en="CT Head",
                priority=ExamOrder.Priority.ROUTINE,
                status=ExamOrder.Status.REGISTERED,
            )
        self.msg_a1 = _make_vital_message("MRN-100", pulse_rate=70, spo2=97)
        self.msg_a2 = _make_vital_message("MRN-100", pulse_rate=80, spo2=99)
        self.msg_b1 = _make_vital_message("MRN-200", pulse_rate=60, spo2=95)

    def test_patient_detail_links_to_hl7_vitals(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("patients:patient_detail", args=[self.patient_a.pk])
        )
        self.assertEqual(response.status_code, 200)
        vitals_url = reverse("patients:patient_hl7_vitals", args=[self.patient_a.pk])
        self.assertContains(response, vitals_url)

    def test_per_patient_page_shows_only_that_patient_readings(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("patients:patient_hl7_vitals", args=[self.patient_a.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MRN-100")
        self.assertNotContains(response, "MRN-200")
        # Two readings for patient A, averages cover only those two.
        self.assertEqual(response.context["reading_count"], 2)
        self.assertEqual(len(response.context["rows"]), 2)
        pulse_col = next(c for c in response.context["columns"] if c["key"] == "pulse_rate")
        self.assertEqual(pulse_col["average"], "75")

    def test_other_patient_page_is_separate(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("patients:patient_hl7_vitals", args=[self.patient_b.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MRN-200")
        self.assertNotContains(response, "MRN-100")
        self.assertEqual(response.context["reading_count"], 1)

    def test_cross_facility_patient_vitals_not_visible(self):
        other_facility = Facility.objects.create(name="Site B", dicom_ae_title="AE_SITE_B")
        other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="secure-pass-123",
            facility=other_facility,
            is_staff=True,
        )
        self.client.force_login(other_user)
        response = self.client.get(
            reverse("patients:patient_hl7_vitals", args=[self.patient_a.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(
            reverse("patients:patient_hl7_vitals", args=[self.patient_a.pk])
        )
        self.assertEqual(response.status_code, 302)

    def test_overview_page_still_lists_all_patients(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("patients:hl7_vitals"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["reading_count"], 3)
        self.assertContains(response, "MRN-100")
        self.assertContains(response, "MRN-200")
