from django import forms
from django.forms import inlineformset_factory

from .models import (
    Authorization,
    Claim,
    ClaimAppeal,
    ClaimLine,
    Clearinghouse,
    DenialReason,
    FeeSchedule,
    FeeScheduleItem,
    InsurancePayer,
    PatientAccount,
    PatientInsurance,
    PatientStatement,
    Payment,
    PaymentAllocation,
    PaymentDetail,
    PaymentPosting,
    PaymentPlan,
    PaymentPlanInstallment,
    ServiceLine,
)


class InsurancePayerForm(forms.ModelForm):
    class Meta:
        model = InsurancePayer
        fields = [
            "payer_id",
            "name",
            "short_name",
            "payer_type",
            "address_line1",
            "address_line2",
            "city",
            "state_province",
            "postal_code",
            "country",
            "phone",
            "fax",
            "email",
            "website",
            "edi_qualifier",
            "edi_receiver_id",
            "clearinghouse",
            "fee_schedule",
            "default_copay",
            "is_active",
        ]
        widgets = {
            "payer_id": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "EDI Payer ID"}
            ),
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Full legal name"}
            ),
            "short_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Common abbreviation"}
            ),
            "payer_type": forms.Select(attrs={"class": "form-select"}),
            "address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "state_province": forms.TextInput(attrs={"class": "form-control"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "ISO code"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 (555) 123-4567"}
            ),
            "fax": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "website": forms.URLInput(attrs={"class": "form-control"}),
            "edi_qualifier": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "PI, XV, etc."}
            ),
            "edi_receiver_id": forms.TextInput(attrs={"class": "form-control"}),
            "clearinghouse": forms.Select(attrs={"class": "form-select"}),
            "fee_schedule": forms.Select(attrs={"class": "form-select"}),
            "default_copay": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ClearinghouseForm(forms.ModelForm):
    class Meta:
        model = Clearinghouse
        fields = [
            "name",
            "api_endpoint",
            "api_username",
            "api_password",
            "api_key",
            "sender_id",
            "receiver_id",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "api_endpoint": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://..."}
            ),
            "api_username": forms.TextInput(attrs={"class": "form-control"}),
            "api_password": forms.PasswordInput(attrs={"class": "form-control"}),
            "api_key": forms.TextInput(attrs={"class": "form-control"}),
            "sender_id": forms.TextInput(attrs={"class": "form-control"}),
            "receiver_id": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PatientInsuranceForm(forms.ModelForm):
    class Meta:
        model = PatientInsurance
        fields = [
            "patient",
            "payer",
            "policy_number",
            "group_number",
            "plan_type",
            "priority",
            "effective_date",
            "termination_date",
            "subscriber_first_name",
            "subscriber_last_name",
            "subscriber_middle_name",
            "subscriber_dob",
            "subscriber_gender",
            "relationship_to_patient",
            "copay_amount",
            "deductible_remaining",
            "coinsurance_percentage",
            "verified",
            "verification_notes",
        ]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select"}),
            "payer": forms.Select(attrs={"class": "form-select"}),
            "policy_number": forms.TextInput(attrs={"class": "form-control"}),
            "group_number": forms.TextInput(attrs={"class": "form-control"}),
            "plan_type": forms.TextInput(attrs={"class": "form-control"}),
            "priority": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "effective_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "termination_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "subscriber_first_name": forms.TextInput(attrs={"class": "form-control"}),
            "subscriber_last_name": forms.TextInput(attrs={"class": "form-control"}),
            "subscriber_middle_name": forms.TextInput(attrs={"class": "form-control"}),
            "subscriber_dob": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "subscriber_gender": forms.Select(attrs={"class": "form-select"}),
            "relationship_to_patient": forms.Select(attrs={"class": "form-select"}),
            "copay_amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "deductible_remaining": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "coinsurance_percentage": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
            "verified": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "verification_notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }


class AuthorizationForm(forms.ModelForm):
    class Meta:
        model = Authorization
        fields = [
            "exam_order",
            "auth_number",
            "auth_type",
            "status",
            "approved_by",
            "approved_date",
            "valid_from",
            "valid_until",
            "approved_procedures",
            "approved_visits",
            "authorized_amount",
            "denial_reason",
            "denial_code",
            "notes",
        ]
        widgets = {
            "exam_order": forms.Select(attrs={"class": "form-select"}),
            "auth_number": forms.TextInput(attrs={"class": "form-control"}),
            "auth_type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "approved_by": forms.TextInput(attrs={"class": "form-control"}),
            "approved_date": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "valid_from": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "valid_until": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "approved_procedures": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "JSON list of CPT codes",
                }
            ),
            "approved_visits": forms.NumberInput(attrs={"class": "form-control"}),
            "authorized_amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "denial_reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "denial_code": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class PatientAccountForm(forms.ModelForm):
    class Meta:
        model = PatientAccount
        fields = [
            "patient",
            "account_number",
            "account_status",
            "credit_limit",
            "has_payment_plan",
            "monthly_payment",
            "financial_assistance",
            "charity_care",
            "guarantor",
            "notes",
        ]
        widgets = {
            "patient": forms.Select(attrs={"class": "form-select"}),
            "account_number": forms.TextInput(attrs={"class": "form-control"}),
            "account_status": forms.Select(attrs={"class": "form-select"}),
            "credit_limit": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "has_payment_plan": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "monthly_payment": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "financial_assistance": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "charity_care": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "guarantor": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class FeeScheduleForm(forms.ModelForm):
    class Meta:
        model = FeeSchedule
        fields = [
            "name",
            "description",
            "schedule_type",
            "payer",
            "effective_date",
            "expiration_date",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Medicare 2024 National",
                }
            ),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "schedule_type": forms.Select(attrs={"class": "form-select"}),
            "payer": forms.Select(attrs={"class": "form-select"}),
            "effective_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "expiration_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class FeeScheduleItemForm(forms.ModelForm):
    class Meta:
        model = FeeScheduleItem
        fields = [
            "procedure_code",
            "procedure_description",
            "modality",
            "professional_component",
            "technical_component",
            "global_fee",
            "contrast_charge",
            "sedation_charge",
            "revenue_code",
            "default_units",
        ]
        widgets = {
            "procedure_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "CPT/HCPCS Code"}
            ),
            "procedure_description": forms.TextInput(attrs={"class": "form-control"}),
            "modality": forms.Select(attrs={"class": "form-select"}),
            "professional_component": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "technical_component": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "global_fee": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "contrast_charge": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "sedation_charge": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "revenue_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "4-digit revenue code"}
            ),
            "default_units": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
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


# ============================================================================
# SERVICE LINE FORMS (CHARGE CAPTURE)
# ============================================================================

class ServiceLineForm(forms.ModelForm):
    """Form for creating/editing service line items (charge capture)"""
    
    diagnosis_code_1 = forms.CharField(max_length=20, required=True, label="Primary Diagnosis")
    diagnosis_code_2 = forms.CharField(max_length=20, required=False, label="Secondary Diagnosis")
    diagnosis_code_3 = forms.CharField(max_length=20, required=False, label="Diagnosis 3")
    diagnosis_code_4 = forms.CharField(max_length=20, required=False, label="Diagnosis 4")
    
    modifier_1 = forms.CharField(max_length=5, required=False)
    modifier_2 = forms.CharField(max_length=5, required=False)
    modifier_3 = forms.CharField(max_length=5, required=False)
    modifier_4 = forms.CharField(max_length=5, required=False)
    
    class Meta:
        model = ServiceLine
        fields = [
            'exam_order',
            'patient_account',
            'service_date',
            'procedure_code',
            'procedure_name',
            'quantity',
            'units_of_service',
            'unit_price',
            'total_charge',
            'rendering_provider',
            'supervising_provider',
            'place_of_service',
            'facility',
            'billing_status',
            'audit_notes',
        ]
        widgets = {
            'exam_order': forms.Select(attrs={'class': 'form-select'}),
            'patient_account': forms.Select(attrs={'class': 'form-select'}),
            'service_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'procedure_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'CPT/HCPCS Code'}),
            'procedure_name': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'units_of_service': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., UN, MIN'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'total_charge': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'rendering_provider': forms.Select(attrs={'class': 'form-select'}),
            'supervising_provider': forms.Select(attrs={'class': 'form-select'}),
            'place_of_service': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'POS code'}),
            'facility': forms.Select(attrs={'class': 'form-select'}),
            'billing_status': forms.Select(attrs={'class': 'form-select'}),
            'audit_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing an existing instance, populate diagnosis and modifier fields
        if self.instance and self.instance.pk:
            diagnosis_codes = self.instance.diagnosis_codes or []
            modifiers = self.instance.modifiers or []
            
            for i in range(min(4, len(diagnosis_codes))):
                field_name = f'diagnosis_code_{i+1}'
                if field_name in self.fields:
                    self.initial[field_name] = diagnosis_codes[i].get('code', '') if isinstance(diagnosis_codes[i], dict) else diagnosis_codes[i]
            
            for i in range(min(4, len(modifiers))):
                field_name = f'modifier_{i+1}'
                if field_name in self.fields:
                    self.initial[field_name] = modifiers[i]
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Build diagnosis codes list
        diagnosis_codes = []
        for i in range(1, 5):
            code = cleaned_data.get(f'diagnosis_code_{i}')
            if code:
                diagnosis_codes.append({
                    'code': code,
                    'primary': (i == 1)
                })
        cleaned_data['diagnosis_codes'] = diagnosis_codes
        
        # Build modifiers list
        modifiers = []
        for i in range(1, 5):
            mod = cleaned_data.get(f'modifier_{i}')
            if mod:
                modifiers.append(mod.strip())
        cleaned_data['modifiers'] = modifiers
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # Set diagnosis_codes and modifiers from cleaned data
        instance.diagnosis_codes = self.cleaned_data.get('diagnosis_codes', [])
        instance.modifiers = self.cleaned_data.get('modifiers', [])
        
        if commit:
            instance.save()
        return instance


# Inline FormSet for managing service lines within an exam order
# Note: Defined in views when needed due to lazy model reference
ServiceLineFormSet = None


# ============================================================================
# CLAIM FORMS
# ============================================================================

class ClaimForm(forms.ModelForm):
    """Form for creating/editing insurance claims"""
    
    class Meta:
        model = Claim
        fields = [
            'patient_account',
            'payer',
            'claim_type',
            'date_of_service_from',
            'date_of_service_to',
            'total_charges',
            'expected_insurance',
            'expected_patient',
            'notes',
        ]
        widgets = {
            'patient_account': forms.Select(attrs={'class': 'form-select'}),
            'payer': forms.Select(attrs={'class': 'form-select'}),
            'claim_type': forms.Select(attrs={'class': 'form-select'}),
            'date_of_service_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_of_service_to': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'total_charges': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expected_insurance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expected_patient': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter payers to active ones only
        self.fields['payer'].queryset = InsurancePayer.objects.filter(is_active=True)


# Inline FormSet for managing claim lines within a claim
ClaimLineFormSet = inlineformset_factory(
    Claim,
    ClaimLine,
    fields=['service_line', 'cpt_code', 'modifiers', 'diagnosis_pointers', 
            'charge_amount', 'allowed_amount', 'paid_amount', 'adjustment_amount', 'status'],
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


# ============================================================================
# CLAIM LINE FORMS
# ============================================================================

class ClaimLineForm(forms.ModelForm):
    """Form for individual claim line items"""
    
    diagnosis_ptr_1 = forms.IntegerField(required=False, min_value=1, max_value=12, label="Diag Pointer 1")
    diagnosis_ptr_2 = forms.IntegerField(required=False, min_value=1, max_value=12, label="Diag Pointer 2")
    diagnosis_ptr_3 = forms.IntegerField(required=False, min_value=1, max_value=12, label="Diag Pointer 3")
    diagnosis_ptr_4 = forms.IntegerField(required=False, min_value=1, max_value=12, label="Diag Pointer 4")
    
    modifier_1 = forms.CharField(max_length=5, required=False)
    modifier_2 = forms.CharField(max_length=5, required=False)
    modifier_3 = forms.CharField(max_length=5, required=False)
    modifier_4 = forms.CharField(max_length=5, required=False)
    
    class Meta:
        model = ClaimLine
        fields = [
            'service_line',
            'cpt_code',
            'charge_amount',
            'allowed_amount',
            'paid_amount',
            'adjustment_amount',
            'status',
            'denial_code',
            'denial_reason',
        ]
        widgets = {
            'service_line': forms.Select(attrs={'class': 'form-select'}),
            'cpt_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'CPT/HCPCS Code'}),
            'charge_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'allowed_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'paid_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'adjustment_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'denial_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'CARC code'}),
            'denial_reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # Populate diagnosis pointers
            pointers = self.instance.diagnosis_pointers or []
            for i in range(min(4, len(pointers))):
                field_name = f'diagnosis_ptr_{i+1}'
                if field_name in self.fields:
                    self.initial[field_name] = pointers[i]
            
            # Populate modifiers
            modifiers = self.instance.modifiers or []
            for i in range(min(4, len(modifiers))):
                field_name = f'modifier_{i+1}'
                if field_name in self.fields:
                    self.initial[field_name] = modifiers[i]
    
    def clean(self):
        cleaned_data = super().clean()
        
        # Build diagnosis pointers list
        pointers = []
        for i in range(1, 5):
            ptr = cleaned_data.get(f'diagnosis_ptr_{i}')
            if ptr:
                pointers.append(ptr)
        cleaned_data['diagnosis_pointers'] = pointers
        
        # Build modifiers list
        modifiers = []
        for i in range(1, 5):
            mod = cleaned_data.get(f'modifier_{i}')
            if mod:
                modifiers.append(mod.strip())
        cleaned_data['modifiers'] = modifiers
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.diagnosis_pointers = self.cleaned_data.get('diagnosis_pointers', [])
        instance.modifiers = self.cleaned_data.get('modifiers', [])
        
        if commit:
            instance.save()
        return instance



# ============================================================================
# PAYMENT POSTING FORMS
# ============================================================================

class PaymentPostingForm(forms.ModelForm):
    """Form for creating/editing payment postings from ERA/EOB"""

    class Meta:
        model = PaymentPosting
        fields = [
            'claim',
            'posting_date',
            'payment_method',
            'check_number',
            'payment_amount',
            'era_trace_number',
            'era_file_reference',
            'payer',
            'status',
        ]
        widgets = {
            'claim': forms.Select(attrs={'class': 'form-select'}),
            'posting_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'check_number': forms.TextInput(attrs={'class': 'form-control'}),
            'payment_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'era_trace_number': forms.TextInput(attrs={'class': 'form-control'}),
            'era_file_reference': forms.TextInput(attrs={'class': 'form-control'}),
            'payer': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter payers to active ones only
        self.fields['payer'].queryset = InsurancePayer.objects.filter(is_active=True)
        # Filter claims to those that are submitted or accepted
        if hasattr(kwargs.get('initial'), 'get') or hasattr(self, 'request'):
            tenant = getattr(self, 'request', None) and getattr(self.request, 'tenant', None)
            if tenant:
                self.fields['claim'].queryset = Claim.objects.filter(
                    tenant=tenant,
                    status__in=['SUBMITTED', 'ACCEPTED', 'PARTIAL']
                )


class PaymentDetailForm(forms.ModelForm):
    """Form for payment details per claim line"""

    class Meta:
        model = PaymentDetail
        fields = [
            'claim_line',
            'paid_amount',
            'adjustments',
            'patient_deductible',
            'patient_copay',
            'patient_coinsurance',
            'is_denied',
            'denial_code',
            'denial_reason',
            'remark_codes',
        ]
        widgets = {
            'claim_line': forms.Select(attrs={'class': 'form-select'}),
            'paid_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'adjustments': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'JSON array of adjustments'}),
            'patient_deductible': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'patient_copay': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'patient_coinsurance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_denied': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'denial_code': forms.TextInput(attrs={'class': 'form-control'}),
            'denial_reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'remark_codes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'JSON array of remark codes'}),
        }


# Inline FormSet for managing payment details within a payment posting
PaymentDetailFormSet = inlineformset_factory(
    PaymentPosting,
    PaymentDetail,
    form=PaymentDetailForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


# ============================================================================
# PATIENT PAYMENT FORMS
# ============================================================================

class PaymentForm(forms.ModelForm):
    """Form for creating/editing patient payments"""

    class Meta:
        model = Payment
        fields = [
            'patient_account',
            'payment_date',
            'amount',
            'payment_method',
            'check_number',
            'card_last_four',
            'card_type',
            'transaction_id',
            'notes',
        ]
        widgets = {
            'patient_account': forms.Select(attrs={'class': 'form-select'}),
            'payment_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'check_number': forms.TextInput(attrs={'class': 'form-control'}),
            'card_last_four': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 4}),
            'card_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Visa, MasterCard'}),
            'transaction_id': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter patient accounts to active ones
        if hasattr(self, 'request'):
            tenant = getattr(self.request, 'tenant', None)
            if tenant:
                self.fields['patient_account'].queryset = PatientAccount.objects.filter(
                    tenant=tenant,
                    account_status__in=['ACTIVE', 'PENDING_INSURANCE', 'PENDING_FOLLOWUP']
                )


class PaymentAllocationForm(forms.ModelForm):
    """Form for allocating payments to service lines"""

    class Meta:
        model = PaymentAllocation
        fields = [
            'service_line',
            'allocated_amount',
            'notes',
        ]
        widgets = {
            'service_line': forms.Select(attrs={'class': 'form-select'}),
            'allocated_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


# Inline FormSet for managing allocations within a payment
PaymentAllocationFormSet = inlineformset_factory(
    Payment,
    PaymentAllocation,
    form=PaymentAllocationForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


# ============================================================================
# PATIENT STATEMENT FORMS
# ============================================================================

class PatientStatementForm(forms.ModelForm):
    """Form for creating/editing patient billing statements"""

    class Meta:
        model = PatientStatement
        fields = [
            'patient_account',
            'statement_date',
            'due_date',
            'service_date_from',
            'service_date_to',
            'previous_balance',
            'charges_this_period',
            'payments_this_period',
            'adjustments_this_period',
            'current_balance',
            'minimum_payment_due',
            'delivery_method',
            'status',
            'notes',
        ]
        widgets = {
            'patient_account': forms.Select(attrs={'class': 'form-select'}),
            'statement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'service_date_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'service_date_to': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'previous_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'charges_this_period': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payments_this_period': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'adjustments_this_period': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'current_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'minimum_payment_due': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'delivery_method': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter patient accounts to active ones with balances
        if hasattr(self, 'request'):
            tenant = getattr(self.request, 'tenant', None)
            if tenant:
                self.fields['patient_account'].queryset = PatientAccount.objects.filter(
                    tenant=tenant,
                    current_balance__gt=0
                )


# ============================================================================
# PAYMENT PLAN FORMS
# ============================================================================

class PaymentPlanForm(forms.ModelForm):
    """Form for creating/editing patient payment plans"""

    class Meta:
        model = PaymentPlan
        fields = [
            'patient_account',
            'total_amount',
            'remaining_balance',
            'monthly_payment',
            'first_payment_date',
            'payment_day',
            'number_of_payments',
            'agreement_signed',
            'agreement_date',
            'notes',
        ]
        widgets = {
            'patient_account': forms.Select(attrs={'class': 'form-select'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'remaining_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monthly_payment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'first_payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_day': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 28}),
            'number_of_payments': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'agreement_signed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'agreement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter patient accounts to active ones
        if hasattr(self, 'request'):
            tenant = getattr(self.request, 'tenant', None)
            if tenant:
                self.fields['patient_account'].queryset = PatientAccount.objects.filter(
                    tenant=tenant,
                    account_status='ACTIVE',
                    current_balance__gt=0
                )


class PaymentPlanInstallmentForm(forms.ModelForm):
    """Form for managing payment plan installments"""

    class Meta:
        model = PaymentPlanInstallment
        fields = [
            'installment_number',
            'due_date',
            'amount_due',
            'status',
            'payment',
            'paid_date',
            'notes',
        ]
        widgets = {
            'installment_number': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'amount_due': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'payment': forms.Select(attrs={'class': 'form-select'}),
            'paid_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


# Inline FormSet for managing installments within a payment plan
PaymentPlanInstallmentFormSet = inlineformset_factory(
    PaymentPlan,
    PaymentPlanInstallment,
    form=PaymentPlanInstallmentForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


class DenialReasonForm(forms.ModelForm):
    """Form for managing denial reason codes"""

    class Meta:
        model = DenialReason
        fields = [
            'code_system',
            'code',
            'description',
            'category',
            'requires_appeal',
            'appeal_deadline_days',
            'common_resolution',
            'is_active',
        ]
        widgets = {
            'code_system': forms.Select(attrs={'class': 'form-select'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 10}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'requires_appeal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'appeal_deadline_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'common_resolution': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ClaimAppealForm(forms.ModelForm):
    """Form for creating and managing claim appeals"""

    class Meta:
        model = ClaimAppeal
        fields = [
            'claim',
            'claim_line',
            'appeal_level',
            'status',
            'filed_date',
            'due_date',
            'reason',
            'supporting_documents',
            'decision',
            'reversal_amount',
        ]
        widgets = {
            'claim': forms.Select(attrs={'class': 'form-select'}),
            'claim_line': forms.Select(attrs={'class': 'form-select'}),
            'appeal_level': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'filed_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'supporting_documents': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 
                'placeholder': 'Enter document references as JSON array, e.g., ["doc1.pdf", "doc2.pdf"]'}),
            'decision': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'reversal_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter claims to denied ones
        if hasattr(self, 'request'):
            tenant = getattr(self.request, 'tenant', None)
            if tenant:
                self.fields['claim'].queryset = Claim.objects.filter(
                    tenant=tenant,
                    status='DENIED'
                )
                self.fields['claim_line'].queryset = ClaimLine.objects.filter(
                    claim__tenant=tenant,
                    status='DENIED'
                )
