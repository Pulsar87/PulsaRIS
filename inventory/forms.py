from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from orders.models import ExamOrder

from .models import (
    StockReceipt,
    InventoryItem, 
    StockReceiptItem,
    StockTransaction,
    Supplier,
)


# class StockTransactionForm(forms.Form):
#     transaction_type = forms.ChoiceField(
#         choices=[
#             (StockTransaction.TransactionType.IN, "Stock In"),
#             (StockTransaction.TransactionType.OUT, "Stock Out"),
#         ],
#         widget=forms.Select(attrs={"class": "form-select"}),
#     )
#     quantity = forms.DecimalField(
#         min_value=0.001,
#         max_digits=12,
#         decimal_places=3,
#         widget=forms.NumberInput(
#             attrs={
#                 "class": "form-control",
#                 "min": "0.001",
#                 "step": "0.001",
#                 "placeholder": "0.000",
#             }
#         ),
#     )
#     reference_exam = forms.ModelChoiceField(
#         queryset=ExamOrder.objects.all().order_by("-created_at"),
#         required=False,
#         empty_label="No exam reference",
#         label="Reference exam (optional)",
#         widget=forms.Select(attrs={"class": "form-select"}),
#     )


class StockTransactionForm(forms.ModelForm):
    """Create / edit a stock ledger entry (In, Out or Adjustment)."""

    class Meta:
        model = StockTransaction
        fields = ["item", "transaction_type", "quantity", "exam", "notes"]
        widgets = {
            "item": forms.Select(attrs={"class": "form-select"}),
            "transaction_type": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0.001",
                    "step": "0.001",
                    "placeholder": "0.000",
                }
            ),
            "exam": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = InventoryItem.objects.filter(
            is_active=True
        ).select_related("category")
        self.fields["item"].empty_label = None
        self.fields["exam"].queryset = ExamOrder.objects.all().order_by(
            "-created_at"
        )[:500]
        self.fields["exam"].empty_label = "No exam reference"
        self.fields["exam"].required = False

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity == 0:
            raise forms.ValidationError("Quantity cannot be zero.")
        return quantity

    def clean(self):
        cleaned = super().clean()
        transaction_type = cleaned.get("transaction_type")
        quantity = cleaned.get("quantity")
        if quantity is not None and transaction_type:
            if transaction_type in (
                StockTransaction.TransactionType.IN,
                StockTransaction.TransactionType.OUT,
            ) and quantity <= 0:
                self.add_error(
                    "quantity", "Quantity must be greater than zero."
                )
            elif (
                transaction_type == StockTransaction.TransactionType.ADJUSTMENT
                and quantity == 0
            ):
                self.add_error(
                    "quantity", "An adjustment cannot be zero."
                )
        return cleaned


class SupplierForm(forms.ModelForm):
    """Create / edit a seller (vendor) that stock is imported from."""

    class Meta:
        model = Supplier
        fields = [
            "name",
            "contact_person",
            "phone",
            "email",
            "address",
            "tax_id",
            "notes",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "tax_id": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class StockReceiptForm(forms.ModelForm):
    """Header of a goods-received note (import from a seller)."""

    class Meta:
        model = StockReceipt
        fields = [
            "supplier",
            "invoice_number",
            "delivery_note",
            "received_date",
            "notes",
        ]
        widgets = {
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "invoice_number": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_note": forms.TextInput(attrs={"class": "form-control"}),
            "received_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 2}
            ),
        }


class StockReceiptItemForm(forms.ModelForm):
    """One imported batch line: item, quantity, price, batch & expiry."""

    class Meta:
        model = StockReceiptItem
        fields = [
            "item",
            "quantity",
            "unit_price",
            "batch_number",
            "manufacture_date",
            "expiry_date",
            "minimum_shelf_life_days",
        ]
        widgets = {
            "item": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control", "min": "0.001", "step": "0.001"}
            ),
            "unit_price": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "step": "0.01"}
            ),
            "batch_number": forms.TextInput(attrs={"class": "form-control"}),
            "manufacture_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "expiry_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "minimum_shelf_life_days": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "step": "1"}
            ),
        }

    def clean_expiry_date(self):
        expiry_date = self.cleaned_data["expiry_date"]
        if expiry_date and expiry_date < timezone.localdate():
            raise forms.ValidationError("This batch is already expired.")
        return expiry_date

    def clean(self):
        cleaned = super().clean()
        expiry = cleaned.get("expiry_date")
        mfg = cleaned.get("manufacture_date")
        if expiry and mfg and expiry <= mfg:
            self.add_error(
                "expiry_date", "Expiry date must be after the manufacture date."
            )
        min_shelf = cleaned.get("minimum_shelf_life_days") or 0
        if expiry:
            days_left = (expiry - timezone.localdate()).days
            if days_left < int(min_shelf):
                self.add_error(
                    "expiry_date",
                    f"Only {days_left} day(s) shelf life left; minimum "
                    f"accepted for this delivery is {min_shelf} days.",
                )
        return cleaned


# NOTE: `extra=0` + `validate_min=True` handled in the view so we can show a
# friendly "add at least one line" error instead of raw formset errors.
StockReceiptItemFormSet = inlineformset_factory(
    parent_model=StockReceipt,
    model=StockReceiptItem,
    form=StockReceiptItemForm,
    fk_name="receipt",
    extra=3,
    min_num=1,
    validate_min=True,
    can_delete=False,
    can_order=False,
)
