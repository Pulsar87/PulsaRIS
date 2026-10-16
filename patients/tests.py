from datetime import date

from django.test import TestCase
from django.urls import reverse

from core.models import Facility, Modality
from orders.models import ExamOrder
from patients.models import Patient
from reports.models import Report
from users.models import User


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
