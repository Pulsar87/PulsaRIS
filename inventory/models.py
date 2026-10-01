import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


def default_receipt_number():
    """Human-friendly sequential receipt number, e.g. GRN-20260731-001."""
    today = timezone.localdate()
    prefix = f"GRN-{today:%Y%m%d}-"
    last = (
        StockReceipt.objects.filter(receipt_number__startswith=prefix)
        .order_by("-receipt_number")
        .values_list("receipt_number", flat=True)
        .first()
    )
    try:
        sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    except (ValueError, IndexError):
        sequence = 1
    return f"{prefix}{sequence:03d}"


class Supplier(models.Model):
    """A vendor/seller that radiology consumables are purchased from."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, unique=True)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    tax_id = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


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
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
        help_text="Default seller this item is purchased from.",
    )
    batch_number = models.CharField(max_length=60, blank=True)
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(
        null=True,
        blank=True,
        help_text="Earliest expiry currently held for this SKU.",
    )
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

    @property
    def days_to_expiry(self):
        if self.expiry_date is None:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self):
        return self.days_to_expiry is not None and self.days_to_expiry < 0

    @property
    def is_expiring_soon(self):
        days = self.days_to_expiry
        return days is not None and 0 <= days <= 90


class StockTransactionQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def include_deleted(self):
        return self.all()


class StockTransactionManager(models.Manager.from_queryset(StockTransactionQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class StockTransaction(models.Model):
    class TransactionType(models.TextChoices):
        IN = "IN", "Stock In"
        OUT = "OUT", "Stock Out"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    objects = StockTransactionManager()
    all_objects = StockTransactionQuerySet.as_manager()

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
    notes = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="deleted_stock_transactions",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["item", "timestamp"]),
            models.Index(fields=["transaction_type", "timestamp"]),
            models.Index(fields=["is_deleted"]),
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

    def soft_delete(self, deleted_by=None):
        """Mark the transaction as deleted without removing the ledger row."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])


class StockReceipt(models.Model):
    """A goods-received note: one delivery from a supplier into inventory."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt_number = models.CharField(
        max_length=30, unique=True, default=default_receipt_number
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="receipts"
    )
    invoice_number = models.CharField(max_length=60, blank=True)
    delivery_note = models.CharField(max_length=60, blank=True)
    received_date = models.DateField(default=timezone.localdate)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_receipts",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "stock receipt"
        verbose_name_plural = "stock receipts"
        indexes = [models.Index(fields=["supplier", "received_date"])]

    def __str__(self):
        return f"{self.receipt_number} ({self.supplier.name})"


class StockReceiptItem(models.Model):
    """One line of a stock receipt: an item, its quantity, batch and expiry."""

    EXPIRY_STATUS_CHOICES = [
        ("OK", "Acceptable"),
        ("WARNING", "Accepted with warning (short shelf life)"),
        ("REJECTED", "Rejected (expired / below minimum shelf life)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt = models.ForeignKey(
        StockReceipt, on_delete=models.CASCADE, related_name="items"
    )
    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="receipt_items"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    total_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    batch_number = models.CharField(max_length=60, blank=True)
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    minimum_shelf_life_days = models.PositiveIntegerField(
        default=90,
        help_text="Deliveries expiring sooner than this are rejected.",
    )
    expiry_status = models.CharField(
        max_length=10, choices=EXPIRY_STATUS_CHOICES, default="OK"
    )
    transaction = models.OneToOneField(
        StockTransaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receipt_item",
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="stock_receipt_item_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.item.name} x {self.quantity}"

    @property
    def days_to_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."
        if self.manufacture_date and self.expiry_date:
            if self.expiry_date <= self.manufacture_date:
                errors["expiry_date"] = (
                    "Expiry date must be after the manufacture date."
                )
            elif self.expiry_date < timezone.localdate():
                errors["expiry_date"] = (
                    "This batch is already expired and cannot be received."
                )
        if errors:
            raise ValidationError(errors)
