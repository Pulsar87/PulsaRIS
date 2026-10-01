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
    # Stock transactions (ledger) — web pages
    path("transactions/", views.transaction_list, name="transaction_list"),
    path("transactions/new/", views.transaction_create, name="transaction_create"),
    path(
        "transactions/<uuid:transaction_id>/edit/",
        views.transaction_edit,
        name="transaction_edit",
    ),
    path(
        "transactions/<uuid:transaction_id>/delete/",
        views.transaction_delete,
        name="transaction_delete",
    ),
    # Suppliers (sellers)
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path(
        "suppliers/<uuid:supplier_id>/edit/",
        views.supplier_edit,
        name="supplier_edit",
    ),
    # Import from sellers (goods received notes)
    path("receipts/", views.receipt_list, name="stock_receipt_list"),
    path(
        "receipts/new/",
        views.stock_receipt_create,
        name="stock_receipt_create",
    ),
    path(
        "receipts/<uuid:receipt_id>/",
        views.stock_receipt_detail,
        name="stock_receipt_detail",
    ),
]
