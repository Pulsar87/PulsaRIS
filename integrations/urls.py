"""URL configuration for the integrations app.

``hl7_urls`` is included under ``/integrations/`` in ``config/urls.py``;
``api_urlpatterns`` under ``/api/integrations/`` (DRF, token/session auth).
"""

from django.urls import path

from integrations import views_hl7
from integrations.hl7 import api as hl7_api

app_name = "integrations"

hl7_urls = [
    path("hl7/messages/", views_hl7.message_list, name="hl7_message_list"),
    path("hl7/messages/<int:pk>/", views_hl7.message_detail, name="hl7_message_detail"),
]

api_urlpatterns = [
    path("hl7/messages/", hl7_api.HL7MessageListView.as_view(), name="hl7_api_message_list"),
    path("hl7/messages/<int:pk>/", hl7_api.HL7MessageDetailView.as_view(), name="hl7_api_message_detail"),
    path("hl7/ingest/", hl7_api.HL7IngestView.as_view(), name="hl7_api_ingest"),
]
