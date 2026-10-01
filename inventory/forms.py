from django import forms

from orders.models import ExamOrder

from .models import StockTransaction


class StockTransactionForm(forms.Form):
    transaction_type = forms.ChoiceField(
        choices=[
            (StockTransaction.TransactionType.IN, "Stock In"),
            (StockTransaction.TransactionType.OUT, "Stock Out"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantity = forms.DecimalField(
        min_value=0.001,
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "0.001",
                "step": "0.001",
                "placeholder": "0.000",
            }
        ),
    )
    reference_exam = forms.ModelChoiceField(
        queryset=ExamOrder.objects.all().order_by("-created_at"),
        required=False,
        empty_label="No exam reference",
        label="Reference exam (optional)",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
