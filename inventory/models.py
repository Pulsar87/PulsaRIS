import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    sku = models.CharField(max_length=50, unique=True)
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="items"
    )
    unit_of_measure = models.CharField(max_length=40)
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    current_stock_level = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["current_stock_level"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(low_stock_threshold__gte=0),
                name="inventory_threshold_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(current_stock_level__gte=0),
                name="inventory_stock_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class StockTransaction(models.Model):
    class TransactionType(models.TextChoices):
        IN = "IN", "Stock In"
        OUT = "OUT", "Stock Out"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="transactions"
    )
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        help_text="Positive for In/Out; signed stock delta for an adjustment.",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_transactions",
    )
    exam = models.ForeignKey(
        "orders.ExamOrder",
        on_delete=models.SET_NULL,
        related_name="stock_transactions",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["item", "timestamp"]),
            models.Index(fields=["transaction_type", "timestamp"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(transaction_type__in=["IN", "OUT", "ADJUSTMENT"]),
                name="stock_transaction_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(quantity__gt=0)
                    | Q(
                        transaction_type="ADJUSTMENT",
                        quantity__lt=0,
                    )
                ),
                name="stock_transaction_quantity_valid",
            ),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()}: {self.item} ({self.quantity})"
