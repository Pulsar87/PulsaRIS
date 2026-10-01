from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.inventory_dashboard, name="dashboard"),
    path("items/", views.inventory_list, name="inventory_list"),
    path(
        "items/<uuid:item_id>/update/",
        views.stock_update,
        name="stock_update",
    ),
    path("stock-in/", views.stock_in, name="stock_in"),
    path("adjustments/", views.stock_adjustment, name="stock_adjustment"),
    path("consume-exam/", views.exam_consumption, name="exam_consumption"),
]
