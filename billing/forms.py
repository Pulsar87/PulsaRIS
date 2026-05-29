from django import forms
from django.forms import inlineformset_factory
from .models import FeeSchedule, FeeScheduleItem


class FeeScheduleForm(forms.ModelForm):
    class Meta:
        model = FeeSchedule
        fields = [
            'name', 'code', 'description', 'schedule_type', 
            'payer', 'effective_date', 'expiration_date', 
            'is_active', 'currency'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Medicare 2024 National'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., MED-2024-NAT'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'schedule_type': forms.Select(attrs={'class': 'form-select'}),
            'payer': forms.Select(attrs={'class': 'form-select'}),
            'effective_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expiration_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
        }


class FeeScheduleItemForm(forms.ModelForm):
    class Meta:
        model = FeeScheduleItem
        fields = [
            'procedure_code', 'procedure_name', 'modifier', 
            'professional_fee', 'technical_fee', 'global_fee', 
            'unit_of_service', 'description'
        ]
        widgets = {
            'procedure_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'CPT/HCPCS Code'}),
            'procedure_name': forms.TextInput(attrs={'class': 'form-control'}),
            'modifier': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 26, TC'}),
            'professional_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'technical_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'global_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'unit_of_service': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


# Inline FormSet for managing items within a fee schedule
FeeScheduleItemFormSet = inlineformset_factory(
    FeeSchedule,
    FeeScheduleItem,
    form=FeeScheduleItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
