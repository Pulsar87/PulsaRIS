from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from .models import Clearinghouse
from .views import ClearinghouseListView


class BillingTenantlessViewTests(SimpleTestCase):
    def test_clearinghouse_list_does_not_require_request_tenant(self):
        request = RequestFactory().get("/billing/clearinghouses/")
        request.user = SimpleNamespace(is_authenticated=True)
        view = ClearinghouseListView()
        view.setup(request)
        queryset = Mock()
        queryset.order_by.return_value = queryset

        with patch.object(Clearinghouse.objects, "all", return_value=queryset):
            response_queryset = view.get_queryset()

        self.assertIs(response_queryset, queryset)
        queryset.order_by.assert_called_once_with("name")
