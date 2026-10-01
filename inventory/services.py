from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import transaction

from .models import InventoryItem, StockTransaction


class InventoryError(ValueError):
    """Base exception for invalid inventory operations."""


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
