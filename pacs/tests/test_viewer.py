from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from clinic.models import FacilityAssignment
from core.models import Facility
from license.models import LicenseActivation
from pacs.models import PACSStudy, StudyStatus


class PacsViewerTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        LicenseActivation.objects.create(
            pk=1,
            expiry_date=date.today() + timedelta(days=365),
            signature="TESTSIG",
            max_orders=None,
        )
        self.facility = Facility.objects.create(
            name="Viewer Facility A",
            dicom_ae_title="VIEWER_AE_A",
        )
        self.other_facility = Facility.objects.create(
            name="Viewer Facility B",
            dicom_ae_title="VIEWER_AE_B",
        )
        self.provider = user_model.objects.create_user(
            username="viewer_provider_a",
            email="viewer-a@example.test",
            password="test-password",
            facility=self.facility,
        )
        self.provider_b = user_model.objects.create_user(
            username="viewer_provider_b",
            email="viewer-b@example.test",
            password="test-password",
            facility=self.other_facility,
        )
        FacilityAssignment.objects.create(
            user=self.provider,
            facility=self.facility,
            role_at_facility="PROVIDER",
            start_date="2026-01-01",
        )
        FacilityAssignment.objects.create(
            user=self.provider_b,
            facility=self.other_facility,
            role_at_facility="PROVIDER",
            start_date="2026-01-01",
        )
        self.study = PACSStudy.objects.create(
            study_instance_uid="1.2.840.113619.2.55.3.77777.1",
            facility=self.facility,
            orthanc_study_id="orthanc-study-1",
            status=StudyStatus.AVAILABLE,
        )
        self.client.force_login(self.provider)

    @patch("pacs.viewer_views.record_audit")
    def test_viewer_renders_deep_link_and_study_scoped_dicomweb_roots(
        self, _mock_record_audit
    ):
        response = self.client.get(
            reverse("pacs:study_viewer", kwargs={"pk": self.study.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["router_basename"],
            "/pacs",
        )
        self.assertEqual(
            response.context["qido_root"],
            "/pacs/viewer/dicomweb/orthanc-study-1",
        )
        self.assertContains(response, "qidoSupportsIncludeField: true")
        self.assertContains(response, "window.history.replaceState")
        self.assertIn("routerBasename: '/pacs'", response.content.decode())
        self.assertContains(response, "'/viewer/' + encodeURIComponent(uid)")

    @patch("pacs.viewer_views.record_audit")
    def test_native_ohif_route_is_refresh_safe_and_facility_scoped(
        self, _mock_record_audit
    ):
        viewer_url = reverse(
            "pacs:study_viewer_uid",
            kwargs={"study_uid": self.study.study_instance_uid},
        )
        response = self.client.get(viewer_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["study"], self.study)

        self.client.force_login(self.provider_b)
        self.assertEqual(self.client.get(viewer_url).status_code, 404)

    def test_query_string_entry_redirects_to_native_ohif_route(self):
        query_url = reverse("pacs:study_viewer_query").rstrip("/")
        response = self.client.get(
            query_url,
            {"studyInstanceUIDs": self.study.study_instance_uid},
        )
        self.assertRedirects(
            response,
            reverse(
                "pacs:study_viewer_uid",
                kwargs={"study_uid": self.study.study_instance_uid},
            ),
            fetch_redirect_response=False,
        )

        self.client.force_login(self.provider_b)
        self.assertEqual(
            self.client.get(
                query_url,
                {"studyInstanceUIDs": self.study.study_instance_uid},
            ).status_code,
            404,
        )

    def test_query_string_entry_rejects_missing_or_multiple_study_uids(self):
        query_url = reverse("pacs:study_viewer_query")
        self.assertEqual(self.client.get(query_url).status_code, 400)
        self.assertEqual(
            self.client.get(
                query_url,
                {"StudyInstanceUIDs": "1.2.3;1.2.4"},
            ).status_code,
            400,
        )

    @patch("pacs.viewer_views.record_audit")
    def test_viewer_deep_link_serves_same_study_and_rejects_uid_mismatch(
        self, _mock_record_audit
    ):
        matching_url = reverse(
            "pacs:study_viewer_study",
            kwargs={
                "pk": self.study.pk,
                "study_uid": self.study.study_instance_uid,
            },
        )
        self.assertEqual(self.client.get(matching_url).status_code, 200)

        mismatched_url = reverse(
            "pacs:study_viewer_study",
            kwargs={"pk": self.study.pk, "study_uid": "1.2.3.4"},
        )
        self.assertEqual(self.client.get(mismatched_url).status_code, 404)

    @override_settings(
        PACS_ORTHANC_API_URL="http://orthanc:8042",
        PACS_ORTHANC_REST_USER="ris-service",
        PACS_ORTHANC_REST_PASSWORD="test-secret",
        PACS_RETRIEVE_TIMEOUT_SECONDS=10,
    )
    @patch("pacs.dicomweb_proxy.urllib.request.urlopen")
    def test_qido_proxy_forces_study_uid_and_forwards_standard_path(self, urlopen):
        upstream = urlopen.return_value.__enter__.return_value
        upstream.status = 200
        upstream.headers.items.return_value = [
            ("Content-Type", "application/dicom+json"),
        ]
        upstream.read.return_value = b"[]"

        proxy_url = reverse(
            "pacs:dicomweb_proxy",
            kwargs={"scope_id": "orthanc-study-1", "path": "studies"},
        )
        response = self.client.get(proxy_url, {"includefield": "00080060"})

        self.assertEqual(response.status_code, 200)
        request = urlopen.call_args.args[0]
        parsed = urlparse(request.full_url)
        self.assertEqual(parsed.path, "/dicom-web/studies")
        self.assertEqual(
            parse_qs(parsed.query)["StudyInstanceUID"],
            [self.study.study_instance_uid],
        )
        self.assertEqual(
            parse_qs(parsed.query)["includefield"],
            ["00080060"],
        )
        self.assertIn("no-store", response["Cache-Control"])

    @override_settings(
        PACS_ORTHANC_API_URL="http://orthanc:8042",
        PACS_ORTHANC_REST_USER="ris-service",
        PACS_ORTHANC_REST_PASSWORD="test-secret",
        PACS_RETRIEVE_TIMEOUT_SECONDS=10,
    )
    @patch("pacs.dicomweb_proxy.urllib.request.urlopen")
    def test_wado_proxy_forwards_study_uid_path(self, urlopen):
        upstream = urlopen.return_value.__enter__.return_value
        upstream.status = 200
        upstream.headers.items.return_value = [("Content-Type", "image/jpeg")]
        upstream.read.return_value = b"dicom-frame"
        series_uid = "1.2.840.113619.2.55.3.77777.1.1"
        instance_uid = "1.2.840.113619.2.55.3.77777.1.1.1"
        dicomweb_path = (
            f"studies/{self.study.study_instance_uid}/series/{series_uid}"
            f"/instances/{instance_uid}/frames/1"
        )
        proxy_url = reverse(
            "pacs:dicomweb_proxy",
            kwargs={"scope_id": "orthanc-study-1", "path": dicomweb_path},
        )

        response = self.client.get(proxy_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"dicom-frame")
        self.assertEqual(
            urlparse(urlopen.call_args.args[0].full_url).path,
            f"/dicom-web/{dicomweb_path}",
        )

    @override_settings(
        PACS_ORTHANC_API_URL="http://orthanc:8042",
        PACS_ORTHANC_REST_USER="ris-service",
        PACS_ORTHANC_REST_PASSWORD="test-secret",
    )
    @patch("pacs.dicomweb_proxy.urllib.request.urlopen")
    def test_proxy_rejects_cross_study_uid_before_archive_request(self, urlopen):
        proxy_url = reverse(
            "pacs:dicomweb_proxy",
            kwargs={
                "scope_id": "orthanc-study-1",
                "path": f"studies/{self.study.study_instance_uid}/metadata",
            },
        )
        response = self.client.get(
            proxy_url,
            {"StudyInstanceUID": "1.2.3.4"},
        )

        self.assertEqual(response.status_code, 404)
        urlopen.assert_not_called()

    def test_proxy_cannot_be_used_from_another_facility(self):
        self.client.force_login(self.provider_b)
        proxy_url = reverse(
            "pacs:dicomweb_proxy",
            kwargs={"scope_id": "orthanc-study-1", "path": "studies"},
        )

        self.assertEqual(self.client.get(proxy_url).status_code, 404)

    @patch("pacs.dicomweb_proxy.urllib.request.urlopen")
    def test_proxy_rejects_path_traversal_before_archive_request(self, urlopen):
        proxy_url = reverse(
            "pacs:dicomweb_proxy",
            kwargs={
                "scope_id": "orthanc-study-1",
                "path": f"studies/{self.study.study_instance_uid}/../instances",
            },
        )

        self.assertEqual(self.client.get(proxy_url).status_code, 404)
        urlopen.assert_not_called()
