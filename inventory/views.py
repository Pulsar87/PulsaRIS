import json
from json import JSONDecodeError
from urllib.parse import urlencode
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import BooleanField, Case, F, Value, When
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods

from orders.models import ExamOrder

from .forms import StockTransactionForm
from .models import Category, InventoryItem
from .services import (
    InventoryError,
    InsufficientStockError,
    add_stock,
    adjust_stock,
    consume_exam_materials,
    record_stock_movement,
)


def _read_json(request):
    try:
        data = json.loads(request.body)
    except (JSONDecodeError, UnicodeDecodeError):
        raise InventoryError("Request body must contain valid JSON.") from None
    if not isinstance(data, dict):
        raise InventoryError("Request body must be a JSON object.")
    return data


def _item_json(item):
    return {
        "id": str(item.pk),
        "name": item.name,
        "sku": item.sku,
        "barcode": item.barcode,
        "category": item.category.name,
        "unit_of_measure": item.unit_of_measure,
        "current_stock_level": str(item.current_stock_level),
        "low_stock_threshold": str(item.low_stock_threshold),
        "is_low_stock": item.current_stock_level <= item.low_stock_threshold,
    }


@login_required
def inventory_dashboard(request, form=None, selected_item=None, status=200):
    categories = Category.objects.order_by("name")
    items = InventoryItem.objects.select_related("category").all()
    category_filter = request.GET.get("category", "")
    if category_filter:
        try:
            UUID(category_filter)
        except (TypeError, ValueError, AttributeError):
            return HttpResponseBadRequest("Invalid category filter.")
        items = items.filter(category_id=category_filter)
    items = items.annotate(
        is_low_stock=Case(
            When(current_stock_level__lte=F("low_stock_threshold"), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )
    )
    return render(
        request,
        "inventory/inventory_list.html",
        {
            "items": items,
            "categories": categories,
            "category_filter": category_filter,
            "stock_form": form or StockTransactionForm(),
            "selected_item": selected_item,
        },
        status=status,
    )


@login_required
@require_http_methods(["GET"])
def inventory_list(request):
    items = InventoryItem.objects.select_related("category").filter(is_active=True)
    if request.GET.get("low_stock", "").lower() in {"1", "true", "yes"}:
        items = items.filter(current_stock_level__lte=F("low_stock_threshold"))
    return JsonResponse({"items": [_item_json(item) for item in items]})


@login_required
@require_POST
def stock_update(request, item_id):
    item = get_object_or_404(InventoryItem, pk=item_id, is_active=True)
    form = StockTransactionForm(request.POST)
    if not form.is_valid():
        return inventory_dashboard(
            request,
            form=form,
            selected_item=item,
            status=400,
        )

    try:
        entry = record_stock_movement(
            item_id=item.pk,
            transaction_type=form.cleaned_data["transaction_type"],
            quantity=form.cleaned_data["quantity"],
            user=request.user,
            exam=form.cleaned_data["reference_exam"],
        )
    except InsufficientStockError as exc:
        form.add_error("quantity", str(exc))
        return inventory_dashboard(
            request,
            form=form,
            selected_item=item,
            status=409,
        )
    except InventoryError as exc:
        form.add_error(None, str(exc))
        return inventory_dashboard(
            request,
            form=form,
            selected_item=item,
            status=400,
        )

    messages.success(
        request,
        f"{entry.get_transaction_type_display()} recorded for {item.name}. "
        f"Current stock: {entry.item.current_stock_level} {item.unit_of_measure}.",
    )
    url = reverse("inventory:dashboard")
    if request.GET.get("category"):
        url = f"{url}?{urlencode({'category': request.GET['category']})}"
    return redirect(url)


@login_required
@require_http_methods(["POST"])
def stock_in(request):
    try:
        data = _read_json(request)
        transaction = add_stock(
            item_id=data["item_id"], quantity=data["quantity"], user=request.user
        )
    except KeyError as exc:
        return JsonResponse({"error": f"Missing required field: {exc.args[0]}."}, status=400)
    except InventoryError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"error": "Inventory item not found."}, status=404)

    return JsonResponse(
        {
            "transaction_id": str(transaction.pk),
            "item_id": str(transaction.item_id),
            "transaction_type": transaction.transaction_type,
            "quantity": str(transaction.quantity),
            "current_stock_level": str(transaction.item.current_stock_level),
        },
        status=201,
    )


@login_required
@require_http_methods(["POST"])
def stock_adjustment(request):
    try:
        data = _read_json(request)
        entry = adjust_stock(
            item_id=data["item_id"],
            quantity_delta=data["quantity_delta"],
            user=request.user,
        )
    except KeyError as exc:
        return JsonResponse({"error": f"Missing required field: {exc.args[0]}."}, status=400)
    except InsufficientStockError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except InventoryError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"error": "Inventory item not found."}, status=404)

    return JsonResponse(
        {
            "transaction_id": str(entry.pk),
            "item_id": str(entry.item_id),
            "transaction_type": entry.transaction_type,
            "quantity_delta": str(entry.quantity),
            "current_stock_level": str(entry.item.current_stock_level),
        },
        status=201,
    )


@login_required
@require_http_methods(["POST"])
def exam_consumption(request):
    try:
        data = _read_json(request)
        result = consume_exam_materials(
            exam_id=data["exam_id"], items_used=data["items"], user=request.user
        )
    except KeyError as exc:
        return JsonResponse({"error": f"Missing required field: {exc.args[0]}."}, status=400)
    except ExamOrder.DoesNotExist:
        return JsonResponse({"error": "Exam not found."}, status=404)
    except InventoryItem.DoesNotExist:
        return JsonResponse({"error": "Inventory item not found."}, status=404)
    except InsufficientStockError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except InventoryError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(
        {
            "transactions": [
                {
                    "transaction_id": str(entry.pk),
                    "item_id": str(entry.item_id),
                    "quantity": str(entry.quantity),
                    "transaction_type": entry.transaction_type,
                }
                for entry in result["transactions"]
            ],
            "low_stock_items": [
                _item_json(item) for item in result["low_stock_items"]
            ],
        },
        status=201,
    )
