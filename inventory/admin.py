from django.contrib import admin

from .models import (
    Category,
    InventoryItem,
    StockReceipt,
    StockReceiptItem,
    StockTransaction,
    Supplier,
)


class StockReceiptItemInline(admin.TabularInline):
    model = StockReceiptItem
    extra = 0
    readonly_fields = ["transaction"]
    autocomplete_fields = ["item"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_person", "phone", "email", "is_active"]
    search_fields = ["name", "contact_person", "email", "tax_id"]
    list_filter = ["is_active"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "sku",
        "category",
        "current_stock_level",
        "low_stock_threshold",
        "unit_of_measure",
        "expiry_date",
        "is_active",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "sku", "barcode"]
    readonly_fields = ["current_stock_level"]


@admin.register(StockReceipt)
class StockReceiptAdmin(admin.ModelAdmin):
    list_display = [
        "receipt_number",
        "supplier",
        "received_date",
        "invoice_number",
        "received_by",
    ]
    list_filter = ["received_date", "supplier"]
    search_fields = ["receipt_number", "invoice_number", "delivery_note"]
    readonly_fields = ["created_at"]
    inlines = [StockReceiptItemInline]

    def has_add_permission(self, request):
        # Receipts must be created through the web import page so that
        # stock levels and transactions stay in sync.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockReceiptItem)
class StockReceiptItemAdmin(admin.ModelAdmin):
    list_display = ["receipt", "item", "quantity", "batch_number", "expiry_date", "expiry_status"]
    list_filter = ["expiry_status"]
    search_fields = ["item__name", "batch_number"]


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "item",
        "transaction_type",
        "quantity",
        "timestamp",
        "user",
        "exam",
        "is_deleted",
    ]
    list_filter = ["transaction_type", "timestamp", "is_deleted"]
    search_fields = ["item__name", "item__sku", "exam__accession_number"]
    readonly_fields = [
        #"item",
        #"transaction_type",
        #"quantity",
        "timestamp",
        "user",
        "exam",
        "notes",
        "is_deleted",
        "deleted_at",
        "deleted_by",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
