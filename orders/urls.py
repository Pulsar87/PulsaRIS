from django.urls import path

from orders import views

app_name = "orders"

urlpatterns = [
    path("", views.worklist, name="worklist"),
    path("<uuid:pk>/", views.order_detail, name="order_detail"),
    path("add/", views.add_order, name="add_order"),
    path("<uuid:pk>/edit/", views.edit_order, name="edit_order"),
    path("<uuid:pk>/delete/", views.delete_order, name="delete_order"),
    path("api/devices/", views.get_devices, name="get_devices"),
    path(
        "<uuid:pk>/update-status/",
        views.update_order_status,
        name="update_order_status",
    ),
    path(
        "<uuid:pk>/send-worklist/",
        views.send_order_worklist,
        name="send_order_worklist",
    ),
    path(
        "devices/<uuid:device_id>/test-connection/",
        views.test_dicom_connection,
        name="test_dicom_connection",
    ),
]
