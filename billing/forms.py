from django import forms
from django.forms import inlineformset_factory
from .models import FeeSchedule, FeeScheduleItem, InsurancePayer, Clearinghouse, PatientInsurance, Authorization, PatientAccount


class InsurancePayerForm(forms.ModelForm):
    class Meta:
        model = InsurancePayer
        fields = [
            'payer_id', 'name', 'short_name', 'payer_type',
            'address_line1', 'address_line2', 'city', 'state_province',
            'postal_code', 'country', 'phone', 'fax', 'email', 'website',
            'edi_qualifier', 'edi_receiver_id', 'clearinghouse',
            'fee_schedule', 'default_copay', 'is_active'
        ]
        widgets = {
            'payer_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'EDI Payer ID'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full legal name'}),
            'short_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Common abbreviation'}),
            'payer_type': forms.Select(attrs={'class': 'form-select'}),
            'address_line1': forms.TextInput(attrs={'class': 'form-control'}),
            'address_line2': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state_province': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ISO code'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1 (555) 123-4567'}),
            'fax': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'edi_qualifier': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PI, XV, etc.'}),
            'edi_receiver_id': forms.TextInput(attrs={'class': 'form-control'}),
            'clearinghouse': forms.Select(attrs={'class': 'form-select'}),
            'fee_schedule': forms.Select(attrs={'class': 'form-select'}),
            'default_copay': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ClearinghouseForm(forms.ModelForm):
    class Meta:
        model = Clearinghouse
        fields = [
            'name', 'api_endpoint', 'api_username', 'api_password',
            'api_key', 'sender_id', 'receiver_id', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'api_endpoint': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'api_username': forms.TextInput(attrs={'class': 'form-control'}),
            'api_password': forms.PasswordInput(attrs={'class': 'form-control'}),
            'api_key': forms.TextInput(attrs={'class': 'form-control'}),
            'sender_id': forms.TextInput(attrs={'class': 'form-control'}),
            'receiver_id': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PatientInsuranceForm(forms.ModelForm):
    class Meta:
        model = PatientInsurance
        fields = [
            'patient', 'payer', 'policy_number', 'group_number', 'plan_type',
            'priority', 'effective_date', 'termination_date',
            'subscriber_first_name', 'subscriber_last_name', 'subscriber_middle_name',
            'subscriber_dob', 'subscriber_gender', 'relationship_to_patient',
            'copay_amount', 'deductible_remaining', 'coinsurance_percentage',
            'verified', 'verification_notes'
        ]
        widgets = {
            'patient': forms.Select(attrs={'class': 'form-select'}),
            'payer': forms.Select(attrs={'class': 'form-select'}),
            'policy_number': forms.TextInput(attrs={'class': 'form-control'}),
            'group_number': forms.TextInput(attrs={'class': 'form-control'}),
            'plan_type': forms.TextInput(attrs={'class': 'form-control'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'effective_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'termination_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'subscriber_first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'subscriber_last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'subscriber_middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'subscriber_dob': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'subscriber_gender': forms.Select(attrs={'class': 'form-select'}),
            'relationship_to_patient': forms.Select(attrs={'class': 'form-select'}),
            'copay_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'deductible_remaining': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'coinsurance_percentage': forms.NumberInput(attrs={'class': 'form-control'}),
            'verified': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'verification_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class AuthorizationForm(forms.ModelForm):
    class Meta:
        model = Authorization
        fields = [
            'exam_order', 'auth_number', 'auth_type', 'status',
            'approved_by', 'approved_date', 'valid_from', 'valid_until',
            'approved_procedures', 'approved_visits', 'authorized_amount',
            'denial_reason', 'denial_code', 'notes'
        ]
        widgets = {
            'exam_order': forms.Select(attrs={'class': 'form-select'}),
            'auth_number': forms.TextInput(attrs={'class': 'form-control'}),
            'auth_type': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'approved_by': forms.TextInput(attrs={'class': 'form-control'}),
            'approved_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'valid_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'approved_procedures': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'JSON list of CPT codes'}),
            'approved_visits': forms.NumberInput(attrs={'class': 'form-control'}),
            'authorized_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'denial_reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'denial_code': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class PatientAccountForm(forms.ModelForm):
    class Meta:
        model = PatientAccount
        fields = [
            'patient', 'account_number', 'account_status',
            'credit_limit', 'has_payment_plan', 'monthly_payment',
            'financial_assistance', 'charity_care', 'guarantor', 'notes'
        ]
        widgets = {
            'patient': forms.Select(attrs={'class': 'form-select'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'account_status': forms.Select(attrs={'class': 'form-select'}),
            'credit_limit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'has_payment_plan': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'monthly_payment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'financial_assistance': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'charity_care': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'guarantor': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


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
