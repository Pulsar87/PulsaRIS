"""Phase 4 UI tests: URL routing, template rendering and access control.

Synthetic data only — no PHI. Verifies the Phase 4 acceptance criteria at
the HTTP layer: an authorized user can find a received study and open its
detail page; a cross-facility or anonymous user cannot discover or act on
it through URLs or guessed IDs (404/redirect, never content).
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse

from core.models import Device, Facility, Modality
from orders.models import ExamOrder
from patients.models import Patient
from pacs.models import PACSStudy, StudyStatus
from pacs.tests.test_reconciliation import ReconciliationFixtureMixin

User = get_user_model()


class PacsUrlRoutingTests(TestCase):
    """Task 4.x wiring: every pacs: name resolves to the right view."""

    def test_named_routes_resolve(self):
        self.assertEqual(resolve("/pacs/").url_name, "study_list")
        self.assertEqual(
            resolve("/pacs/diagnostics/").url_name, "diagnostics"
        )
        pk = "11111111-2222-3333-4444-555555555555"
        self.assertEqual(resolve(f"/pacs/studies/{pk}/").url_name, "study_detail")
        self.assertEqual(
            resolve(f"/pacs/studies/{pk}/action/").url_name, "study_action"
        )
        self.assertEqual(
            resolve(f"/pacs/studies/{pk}/retrieve/").url_name, "retrieve_dicom"
        )
        self.assertEqual(
            resolve(f"/pacs/studies/{pk}/instances/abc123/file/").url_name,
            "instance_file",
        )

    def test_reverse_roundtrip(self):
        self.assertEqual(reverse("pacs:study_list"), "/pacs/")
        pk = "11111111-2222-3333-4444-555555555555"
        self.assertEqual(
            reverse("pacs:study_detail", kwargs={"pk": pk}),
            f"/pacs/studies/{pk}/",
        )


class PacsViewAccessTests(ReconciliationFixtureMixin, TestCase):
    def setUp(self):
        self.setUpFixtures()

    # ---- study list ----------------------------------------------------

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("pacs:study_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url.lower())

    def test_provider_sees_own_facility_study(self):
        self.client.force_login(self.provider)
        response = self.client.get(reverse("pacs:study_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ACC900")
        self.assertContains(response, "Needs reconciliation")

    def test_other_facility_user_cannot_discover_study(self):
        self.client.force_login(self.provider_b)
        response = self.client.get(reverse("pacs:study_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "ACC900")

    def test_invalid_filters_are_reported_not_crashed(self):
        self.client.force_login(self.provider)
        response = self.client.get(
            reverse("pacs:study_list"),
            {"uid": "not-a-uid!!", "status": "BOGUS", "date_from": "13/99/ABCD"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid characters")
        self.assertContains(response, "Unknown archive status filter")
        self.assertContains(response, "Invalid date format")

    def test_pagination_page_size_is_bounded(self):
        self.client.force_login(self.provider)
        response = self.client.get(
            reverse("pacs:study_list"), {"page_size": "99999", "page": "1"}
        )
        self.assertEqual(response.status_code, 200)
        paginator = response.context["paginator"]
        self.assertLessEqual(paginator.per_page, 100)

    # ---- study detail --------------------------------------------------

    def test_detail_renders_for_owner_facility(self):
        self.client.force_login(self.provider)
        response = self.client.get(
            reverse("pacs:study_detail", kwargs={"pk": self.study.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.study.study_instance_uid)
        self.assertContains(response, "manual review needed")
        # Linkage card present (study is currently unlinked).
        self.assertContains(response, "not linked to any RIS order")

    def test_detail_404_for_cross_facility_user(self):
        self.client.force_login(self.provider_b)
        response = self.client.get(
            reverse("pacs:study_detail", kwargs={"pk": self.study.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_detail_404_for_guessed_random_id(self):
        self.client.force_login(self.superuser)
        import uuid

        response = self.client.get(
            reverse("pacs:study_detail", kwargs={"pk": uuid.uuid4()})
        )
        self.assertEqual(response.status_code, 404)

    def test_view_access_is_audited(self):
        from audit.models import AuditLog

        self.client.force_login(self.provider)
        self.client.get(
            reverse("pacs:study_detail", kwargs={"pk": self.study.pk})
        )
        entry = AuditLog.objects.filter(
            action="pacs.study_view", entity_id=str(self.study.pk)
        )
        self.assertTrue(entry.exists())

    # ---- reconciliation actions over HTTP ------------------------------

    def test_action_requires_post_and_reason(self):
        self.client.force_login(self.superuser)
        url = reverse("pacs:study_action", kwargs={"pk": self.study.pk})
        self.assertEqual(self.client.get(url).status_code, 405)
        # POST without reason → redirected back with an error message.
        response = self.client.post(url, {"action": "escalate"})
        self.assertEqual(response.status_code, 302)

    def test_tech_cannot_reconcile_via_http(self):
        self.client.force_login(self.tech)
        url = reverse("pacs:study_action", kwargs={"pk": self.study.pk})
        response = self.client.post(
            url, {"action": "link", "order_pk": str(self.order.pk), "reason": "r"}
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_link_over_http(self):
        self.client.force_login(self.superuser)
        url = reverse("pacs:study_action", kwargs={"pk": self.study.pk})
        response = self.client.post(
            url,
            {"action": "link", "order_pk": str(self.order.pk), "reason": "verified"},
        )
        self.assertEqual(response.status_code, 302)
        self.study.refresh_from_db()
        self.assertEqual(self.study.matched_order_id, self.order.pk)

    def test_conflicting_link_shows_confirm_page_first(self):
        # Make the DICOM patient id differ from the order MRN so preview_link
        # reports a conflict; the view must render the confirm page instead of
        # silently linking (Task 3.3 rule enforced at the UI layer).
        PACSStudy.objects.filter(pk=self.study.pk).update(
            patient_id_as_received="MRN-DIFFERENT"
        )
        self.client.force_login(self.superuser)
        url = reverse("pacs:study_action", kwargs={"pk": self.study.pk})
        response = self.client.post(
            url,
            {"action": "link", "order_pk": str(self.order.pk), "reason": "verify me"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirm Study Link")
        self.assertContains(response, "patient_id/MRN")
        self.study.refresh_from_db()
        self.assertIsNone(self.study.matched_order_id)

    # ---- retrieval proxy (Task 4.2) ------------------------------------

    @patch("pacs.views.OrthancClient.get_study_archive_zip")
    def test_retrieve_denies_cross_facility_before_archive_call(self, mock_zip):
        self.client.force_login(self.provider_b)
        response = self.client.get(
            reverse("pacs:retrieve_dicom", kwargs={"pk": self.study.pk})
        )
        self.assertEqual(response.status_code, 404)
        mock_zip.assert_not_called()

    @patch("pacs.views.OrthancClient.get_study_archive_zip")
    def test_retrieve_returns_zip_with_no_store_headers(self, mock_zip):
        PACSStudy.objects.filter(pk=self.study.pk).update(
            orthanc_study_id="orthanc-study-1"
        )
        mock_zip.return_value = b"PK\x03\x04fake-zip-bytes"
        self.client.force_login(self.provider)
        response = self.client.get(
            reverse("pacs:retrieve_dicom", kwargs={"pk": self.study.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response.content, b"PK\x03\x04fake-zip-bytes")

    def test_retrieve_without_archive_id_is_409(self):
        self.client.force_login(self.provider)
        response = self.client.get(
            reverse("pacs:retrieve_dicom", kwargs={"pk": self.study.pk})
        )
        self.assertEqual(response.status_code, 409)

    # ---- diagnostics ---------------------------------------------------

    def test_diagnostics_staff_only(self):
        self.client.force_login(self.provider)
        response = self.client.get(reverse("pacs:diagnostics"))
        self.assertEqual(response.status_code, 403)

    @patch("pacs.diagnostics_views_probe", create=True)
    def test_diagnostics_renders_for_superuser(self, _unused):
        with patch("pacs.metrics.OrthancClient.get_statistics") as mock_stats:
            mock_stats.return_value = {"DicomFiles": 1, "DiskSize": 2}
            self.client.force_login(self.superuser)
            response = self.client.get(reverse("pacs:diagnostics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PACS System Diagnostics")
        # No credentials or raw payloads leak into the page.
        self.assertNotContains(response, "password")


class DiagnosticsArchiveInsightTests(ReconciliationFixtureMixin, TestCase):
    """Diagnostics page shows Orthanc archive state (no secrets, no PHI)."""

    def setUp(self):
        self.setUpFixtures()

    def test_archive_version_and_connection_panel_rendered(self):
        with patch("pacs.metrics.OrthancClient.get_statistics") as mock_stats, \
             patch("pacs.metrics.OrthancClient.get_summary") as mock_summary:
            mock_stats.return_value = {
                "DicomFiles": 42, "DiskSize": 1024,
                "ChangesCount": 7, "MemoryUsed": 999,
            }
            mock_summary.return_value = {
                "Name": "PulsaRIS-PACS", "Version": "1.12.7", "ApiVersion": 8,
            }
            self.client.force_login(self.superuser)
            response = self.client.get(reverse("pacs:diagnostics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Image Archive (Orthanc)")
        self.assertContains(response, "PulsaRIS-PACS")   # from GET / summary
        self.assertContains(response, "1.12.7")          # version shown
        self.assertContains(response, "Application")      # connection panel
        self.assertContains(response, "http://orthanc:8042")  # endpoint URL
        # Mirror coverage line appears once archive reports stored files.
        self.assertContains(response, "indexed study rows")

    def test_metrics_include_connection_without_credentials(self):
        from pacs.metrics import collect_metrics

        with patch("pacs.metrics.OrthancClient.get_statistics") as mock_stats, \
             patch("pacs.metrics.OrthancClient.get_summary") as mock_summary:
            mock_stats.return_value = {"DicomFiles": 0}
            mock_summary.return_value = {"Name": "X", "Version": "Y"}
            metrics = collect_metrics()
        conn = metrics["connection"]
        self.assertTrue(conn["api_url"])
        self.assertIn(conn["ae_title"], ("PULSAR_PACS",))
        self.assertIsInstance(conn["rest_user_configured"], bool)
        # Never any secret material in the metric snapshot.
        blob = str(metrics)
        for needle in ("password", "ORTHANC_RIS_PASSWORD", "change-me"):
            self.assertNotIn(needle.lower(), blob.lower())

    def test_summary_failure_does_not_break_health(self):
        """GET / failing must not flip an otherwise-healthy archive card."""
        from pacs.metrics import collect_metrics

        with patch("pacs.metrics.OrthancClient.get_statistics") as mock_stats, \
             patch("pacs.metrics.OrthancClient.get_summary") as mock_summary:
            mock_stats.return_value = {"DicomFiles": 3}
            mock_summary.side_effect = RuntimeError("boom")
            metrics = collect_metrics()
        self.assertEqual(metrics["archive"]["health"], "ok")
        self.assertNotIn("version", metrics["archive"])
