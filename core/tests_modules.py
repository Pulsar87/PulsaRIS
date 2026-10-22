"""Tests for the feature-module registry, browser page and disable gate."""

from django.test import TestCase, override_settings
from django.contrib.auth.models import User

from core import module_registry


class ModuleRegistryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("opsuser", password="pw")

    def test_default_all_installed_enabled(self):
        keys = module_registry.enabled_keys()
        self.assertIn("pacs", keys)
        self.assertIn("clinic", keys)

    @override_settings(ENABLED_MODULES=["clinic", "dashboard"])
    def test_explicit_allowlist(self):
        keys = module_registry.enabled_keys()
        self.assertEqual(keys, {"clinic", "dashboard", "ris"})  # ris always on

    @override_settings(ENABLED_MODULES=["clinic"])
    def test_browser_hides_disabled_modules(self):
        self.client.force_login(self.user)
        resp = self.client.get("/apps/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Clinic", body)
        self.assertNotIn('href="/pacs/', body)

    @override_settings(ENABLED_MODULES=["clinic"])
    def test_disabled_module_url_404(self):
        self.client.force_login(self.user)
        resp = self.client.get("/pacs/")
        self.assertEqual(resp.status_code, 404)

    @override_settings(ENABLED_MODULES=["clinic", "pacs"])
    def test_enabled_module_url_works(self):
        self.client.force_login(self.user)
        resp = self.client.get("/pacs/")
        self.assertEqual(resp.status_code, 200)

    def test_license_feature_mapping(self):
        keys = module_registry.license_features_to_module_keys(["CLINIC", "PACS"])
        self.assertEqual(keys, {"clinic", "pacs"})
