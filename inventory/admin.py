from django.contrib import admin

from .models import Category, InventoryItem, StockTransaction


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
        "is_active",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "sku", "barcode"]
    readonly_fields = ["current_stock_level"]


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "item",
        "transaction_type",
        "quantity",
        "timestamp",
        "user",
        "exam",
    ]
    list_filter = ["transaction_type", "timestamp"]
    search_fields = ["item__name", "item__sku", "exam__accession_number"]
    readonly_fields = [
        "item",
        "transaction_type",
        "quantity",
        "timestamp",
        "user",
        "exam",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
