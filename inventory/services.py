from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from .models import (
    InventoryItem,
    StockReceipt,
    StockReceiptItem,
    StockTransaction,
)


class InventoryError(ValueError):
    """Base exception for invalid inventory operations."""


def apply_transaction_effect(item, transaction_type, quantity):
    """Return the stock level after applying a transaction to ``item``.

    IN adds, OUT subtracts, ADJUSTMENT applies the signed delta.
    """
    if transaction_type == StockTransaction.TransactionType.IN:
        return item.current_stock_level + quantity
    if transaction_type == StockTransaction.TransactionType.OUT:
        return item.current_stock_level - quantity
    return item.current_stock_level + quantity


class InsufficientStockError(InventoryError):
    def __init__(self, item, requested, available):
        self.item = item
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for {item.name}: requested {requested}, "
            f"available {available}."
        )


def _positive_quantity(value):
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InventoryError("Quantity must be a positive number.") from exc
    if (
        not quantity.is_finite()
        or quantity <= 0
        or quantity.as_tuple().exponent < -3
        or quantity >= Decimal("1000000000")
    ):
        raise InventoryError("Quantity must be a positive number.")
    return quantity


def _uuid_value(value, field_name):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise InventoryError(f"{field_name} must be a valid UUID.") from exc


def _item_id(value):
    return _uuid_value(value, "item_id")


@transaction.atomic
def record_stock_movement(item_id, transaction_type, quantity, user, exam=None):
    quantity = _positive_quantity(quantity)
    item_id = _item_id(item_id)
    if transaction_type not in {
        StockTransaction.TransactionType.IN,
        StockTransaction.TransactionType.OUT,
    }:
        raise InventoryError("Transaction type must be IN or OUT.")

    item = InventoryItem.objects.select_for_update().get(pk=item_id)
    if transaction_type == StockTransaction.TransactionType.IN:
        new_level = item.current_stock_level + quantity
        if new_level >= Decimal("1000000000"):
            raise InventoryError("Stock level exceeds the supported maximum.")
    else:
        new_level = item.current_stock_level - quantity
        if new_level < 0:
            raise InsufficientStockError(item, quantity, item.current_stock_level)

    item.current_stock_level = new_level
    item.save(update_fields=["current_stock_level", "updated_at"])
    return StockTransaction.objects.create(
        item=item,
        transaction_type=transaction_type,
        quantity=quantity,
        user=user,
        exam=exam,
    )


@transaction.atomic
def add_stock(item_id, quantity, user):
    quantity = _positive_quantity(quantity)
    item_id = _item_id(item_id)
    item = InventoryItem.objects.select_for_update().get(pk=item_id)
    new_level = item.current_stock_level + quantity
    if new_level >= Decimal("1000000000"):
        raise InventoryError("Stock level exceeds the supported maximum.")
    item.current_stock_level = new_level
    item.save(update_fields=["current_stock_level", "updated_at"])
    return StockTransaction.objects.create(
        item=item,
        transaction_type=StockTransaction.TransactionType.IN,
        quantity=quantity,
        user=user,
    )


@transaction.atomic
def adjust_stock(item_id, quantity_delta, user):
    try:
        delta = Decimal(str(quantity_delta))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InventoryError("Adjustment must be a non-zero number.") from exc
    if (
        not delta.is_finite()
        or delta == 0
        or delta.as_tuple().exponent < -3
        or abs(delta) >= Decimal("1000000000")
    ):
        raise InventoryError("Adjustment must be a non-zero number.")

    item_id = _item_id(item_id)
    item = InventoryItem.objects.select_for_update().get(pk=item_id)
    new_level = item.current_stock_level + delta
    if new_level < 0:
        raise InsufficientStockError(item, abs(delta), item.current_stock_level)
    if new_level >= Decimal("1000000000"):
        raise InventoryError("Stock level exceeds the supported maximum.")

    item.current_stock_level = new_level
    item.save(update_fields=["current_stock_level", "updated_at"])
    return StockTransaction.objects.create(
        item=item,
        transaction_type=StockTransaction.TransactionType.ADJUSTMENT,
        quantity=delta,
        user=user,
    )


@transaction.atomic
def consume_exam_materials(exam_id, items_used, user):
    """Consume a list of {item_id, quantity} entries atomically for one exam."""
    from orders.models import ExamOrder

    exam_id = _uuid_value(exam_id, "exam_id")
    exam = ExamOrder.objects.get(pk=exam_id)
    if not isinstance(items_used, (list, tuple)) or not items_used:
        raise InventoryError("items_used must be a non-empty list.")

    requested = {}
    for entry in items_used:
        if not isinstance(entry, dict) or "item_id" not in entry or "quantity" not in entry:
            raise InventoryError("Each item must include item_id and quantity.")
        item_id = _item_id(entry["item_id"])
        quantity = _positive_quantity(entry["quantity"])
        requested[item_id] = requested.get(item_id, Decimal("0")) + quantity

    locked_items = {
        item.pk: item
        for item in InventoryItem.objects.select_for_update()
        .filter(pk__in=requested)
        .order_by("pk")
    }
    missing_ids = sorted(set(requested) - set(locked_items))
    if missing_ids:
        raise InventoryError(
            f"Unknown inventory item(s): {', '.join(map(str, missing_ids))}."
        )

    for item_id, quantity in requested.items():
        item = locked_items[item_id]
        if item.current_stock_level < quantity:
            raise InsufficientStockError(
                item, quantity, item.current_stock_level
            )

    transactions = []
    low_stock_items = []
    for item_id, quantity in requested.items():
        item = locked_items[item_id]
        item.current_stock_level -= quantity
        item.save(update_fields=["current_stock_level", "updated_at"])
        transactions.append(
            StockTransaction.objects.create(
                item=item,
                transaction_type=StockTransaction.TransactionType.OUT,
                quantity=quantity,
                user=user,
                exam=exam,
            )
        )
        if item.current_stock_level <= item.low_stock_threshold:
            low_stock_items.append(item)

    return {
        "transactions": transactions,
        "low_stock_items": low_stock_items,
    }


def classify_expiry(expiry_date, minimum_shelf_life_days):
    """Return ('OK' | 'WARNING' | 'REJECTED') for a batch expiry date.

    REJECTED  -> already expired, or shelf life shorter than the accepted
                 minimum (e.g. contrast media arriving with <90 days left).
    WARNING   -> acceptable, but expiring within the next 90 days.
    OK        -> normal acceptance.
    """
    if expiry_date is None:
        return "OK"
    today = timezone.localdate()
    days_left = (expiry_date - today).days
    if days_left < 0:
        return "REJECTED"
    if days_left < int(minimum_shelf_life_days or 0):
        return "REJECTED"
    if days_left <= 90:
        return "WARNING"
    return "OK"


@transaction.atomic
def create_stock_receipt(*, supplier, lines, user, invoice_number="",
                         delivery_note="", received_date=None, notes=""):
    """Import goods from a seller into inventory as one stock receipt (GRN).

    ``lines`` is an iterable of dicts with keys:
        item, quantity, unit_price, batch_number, manufacture_date,
        expiry_date, minimum_shelf_life_days (optional, default 90).

    Every accepted line creates a StockTransaction (IN) and raises the
    item's stock level atomically. Expired / short-shelf-life batches are
    rejected and abort the whole receipt (row-level locks serialise
    concurrent receipts for the same SKU). Returns the StockReceipt.
    """
    if not lines:
        raise InventoryError("A receipt must contain at least one item line.")

    parsed_lines = []
    seen_item_ids = set()
    for index, raw in enumerate(lines, start=1):
        item = raw["item"]
        if item.pk in seen_item_ids:
            raise InventoryError(
                f"Line {index}: duplicate item '{item.name}'. "
                "Merge quantities into a single line."
            )
        seen_item_ids.add(item.pk)

        quantity = _positive_quantity(raw.get("quantity"))
        expiry_date = raw.get("expiry_date")
        if expiry_date is None:
            raise InventoryError(
                f"Line {index} ({item.name}): expiry date is required "
                "when importing stock from a seller."
            )
        manufacture_date = raw.get("manufacture_date")
        if manufacture_date and expiry_date <= manufacture_date:
            raise InventoryError(
                f"Line {index} ({item.name}): expiry date must be after "
                "the manufacture date."
            )

        min_shelf = int(raw.get("minimum_shelf_life_days") or 90)
        status = classify_expiry(expiry_date, min_shelf)
        if status == "REJECTED":
            days_left = (expiry_date - timezone.localdate()).days
            raise InventoryError(
                f"Line {index} ({item.name}): batch rejected — only "
                f"{days_left} day(s) shelf life left, minimum accepted is "
                f"{min_shelf}. Expired or near-expiry stock cannot be "
                "imported."
            )

        unit_price = raw.get("unit_price")
        if unit_price is not None:
            try:
                unit_price = Decimal(str(unit_price))
            except InvalidOperation:
                raise InventoryError(
                    f"Line {index}: unit price must be a number."
                ) from None
            if unit_price < 0:
                raise InventoryError(
                    f"Line {index}: unit price cannot be negative."
                )

        parsed_lines.append(
            {
                "item": item,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": (
                    unit_price * quantity if unit_price is not None else None
                ),
                "batch_number": (raw.get("batch_number") or "").strip(),
                "manufacture_date": manufacture_date,
                "expiry_date": expiry_date,
                "minimum_shelf_life_days": min_shelf,
                "expiry_status": status,
            }
        )

    receipt = StockReceipt.objects.create(
        supplier=supplier,
        invoice_number=invoice_number or "",
        delivery_note=delivery_note or "",
        received_date=received_date or timezone.localdate(),
        received_by=user,
        notes=notes or "",
    )

    # Lock all involved items up-front so concurrent receipts/outs on the
    # same SKUs are serialised deterministically.
    locked_items = {
        locked.pk: locked
        for locked in InventoryItem.objects.select_for_update().filter(
            pk__in=seen_item_ids
        )
    }

    for line in parsed_lines:
        item = locked_items[line["item"].pk]
        new_level = item.current_stock_level + line["quantity"]
        if new_level >= Decimal("1000000000"):
            raise InventoryError(
                f"Stock level for {item.name} exceeds the supported maximum."
            )
        item.current_stock_level = new_level
        save_fields = ["current_stock_level", "updated_at"]

        # Keep the earliest known expiry on the master record so dashboards
        # surface FEFO concerns; never move a later date backwards.
        current_expiry = item.expiry_date
        if current_expiry is None or line["expiry_date"] < current_expiry:
            item.expiry_date = line["expiry_date"]
            save_fields.append("expiry_date")
        if line["batch_number"]:
            item.batch_number = line["batch_number"]
            save_fields.append("batch_number")
        if line["manufacture_date"] and not item.manufacture_date:
            item.manufacture_date = line["manufacture_date"]
            save_fields.append("manufacture_date")
        item.save(update_fields=list(dict.fromkeys(save_fields)))

        transaction_entry = StockTransaction.objects.create(
            item=item,
            transaction_type=StockTransaction.TransactionType.IN,
            quantity=line["quantity"],
            user=user,
        )
        StockReceiptItem.objects.create(
            receipt=receipt,
            item=item,
            **{k: v for k, v in line.items() if k != "item"},
            transaction=transaction_entry,
        )

    return receipt
