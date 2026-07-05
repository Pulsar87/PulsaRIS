import json
from decimal import Decimal
from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
    View,
)

from .forms import (
    AuthorizationForm,
    ClaimAppealForm,
    ClaimForm,
    ClaimLineForm,
    ClearinghouseForm,
    DenialReasonForm,
    FeeScheduleForm,
    FeeScheduleItemForm,
    FeeScheduleItemFormSet,
    InsurancePayerForm,
    PatientAccountForm,
    PatientInsuranceForm,
    PaymentAllocationForm,
    PaymentDetailForm,
    PaymentForm,
    PaymentPlanForm,
    PaymentPlanInstallmentForm,
    PaymentPlanInstallmentFormSet,
    PaymentPostingForm,
    PatientStatementForm,
    ServiceLineForm,
)
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
    PaymentPosting,
)

# Import EDI services
try:
    from .edi_services import (
        generate_claim_837,
        process_era_file,
        submit_claim_to_clearinghouse,
    )
    EDI_AVAILABLE = True
except ImportError:
    EDI_AVAILABLE = False


class FeeScheduleListView(LoginRequiredMixin, ListView):
    """List all fee schedules with filtering and search"""

    model = FeeSchedule
    template_name = "billing/fee_schedule_list.html"
    context_object_name = "fee_schedules"
    paginate_by = 25

    def get_queryset(self):
        queryset = FeeSchedule.objects.filter(tenant=self.request.tenant)

        # Filter by status
        status = self.request.GET.get("status")
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "expired":
            queryset = queryset.filter(
                Q(expiration_date__lt=timezone.now().date())
                | Q(effective_date__gt=timezone.now().date())
            )
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)

        # Filter by type
        schedule_type = self.request.GET.get("schedule_type")
        if schedule_type:
            queryset = queryset.filter(schedule_type=schedule_type)

        # Search by name or code
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(code__icontains=search)
                | Q(description__icontains=search)
            )

        return queryset.select_related("payer").order_by("-effective_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_count"] = FeeSchedule.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).count()
        context["total_schedules"] = FeeSchedule.objects.filter(
            tenant=self.request.tenant
        ).count()
        return context


class FeeScheduleDetailView(LoginRequiredMixin, DetailView):
    """Detail view of a fee schedule with all items"""

    model = FeeSchedule
    template_name = "billing/fee_schedule_detail.html"
    context_object_name = "fee_schedule"

    def get_queryset(self):
        return FeeSchedule.objects.filter(tenant=self.request.tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fee_schedule = self.object

        # Get statistics
        context["item_count"] = fee_schedule.items.count()
        context["professional_avg"] = fee_schedule.items.aggregate(
            avg=Sum("professional_component") / Count("id")
        )["avg"] or Decimal("0.00")
        context["technical_avg"] = fee_schedule.items.aggregate(
            avg=Sum("technical_component") / Count("id")
        )["avg"] or Decimal("0.00")
        context["global_avg"] = fee_schedule.items.aggregate(
            avg=Sum("global_fee") / Count("id")
        )["avg"] or Decimal("0.00")

        # Check if active
        today = timezone.now().date()
        context["is_currently_active"] = (
            fee_schedule.is_active
            and fee_schedule.effective_date <= today
            and (
                fee_schedule.expiration_date is None
                or fee_schedule.expiration_date >= today
            )
        )

        return context


class FeeScheduleCreateView(LoginRequiredMixin, CreateView):
    """Create a new fee schedule with items"""

    model = FeeSchedule
    form_class = FeeScheduleForm
    template_name = "billing/fee_schedule_form.html"
    success_url = reverse_lazy("billing:fee_schedule_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["tenant"] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class FeeScheduleUpdateView(LoginRequiredMixin, UpdateView):
    """Update fee schedule header information"""

    model = FeeSchedule
    form_class = FeeScheduleForm
    template_name = "billing/fee_schedule_form.html"
    success_url = reverse_lazy("billing:fee_schedule_list")

    def get_queryset(self):
        return FeeSchedule.objects.filter(tenant=self.request.tenant)

    def form_valid(self, form):
        form.instance.modified_by = self.request.user
        return super().form_valid(form)


class FeeScheduleDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a fee schedule (soft delete by setting inactive)"""

    model = FeeSchedule
    template_name = "billing/fee_schedule_confirm_delete.html"
    success_url = reverse_lazy("billing:fee_schedule_list")

    def get_queryset(self):
        return FeeSchedule.objects.filter(tenant=self.request.tenant)

    def delete(self, request, *args, **kwargs):
        # Soft delete - just deactivate
        fee_schedule = self.get_object()
        fee_schedule.is_active = False
        fee_schedule.save()
        return redirect(self.success_url)


class FeeScheduleItemCreateView(LoginRequiredMixin, CreateView):
    """Add items to a fee schedule"""

    model = FeeScheduleItem
    form_class = FeeScheduleItemForm
    template_name = "billing/fee_schedule_item_form.html"

    def get_success_url(self):
        return reverse_lazy(
            "billing:fee_schedule_detail", kwargs={"pk": self.kwargs["pk"]}
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["tenant"] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        fee_schedule = get_object_or_404(
            FeeSchedule.objects.filter(tenant=self.request.tenant), pk=self.kwargs["pk"]
        )
        form.instance.fee_schedule = fee_schedule
        form.instance.tenant = self.request.tenant
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class FeeScheduleItemUpdateView(LoginRequiredMixin, UpdateView):
    """Update a fee schedule item"""

    model = FeeScheduleItem
    form_class = FeeScheduleItemForm
    template_name = "billing/fee_schedule_item_form.html"

    def get_success_url(self):
        return reverse_lazy(
            "billing:fee_schedule_detail", kwargs={"pk": self.object.fee_schedule.pk}
        )

    def get_queryset(self):
        return FeeScheduleItem.objects.filter(tenant=self.request.tenant)

    def form_valid(self, form):
        form.instance.modified_by = self.request.user
        return super().form_valid(form)


class FeeScheduleItemDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a fee schedule item"""

    model = FeeScheduleItem
    template_name = "billing/fee_schedule_item_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy(
            "billing:fee_schedule_detail", kwargs={"pk": self.object.fee_schedule.pk}
        )

    def get_queryset(self):
        return FeeScheduleItem.objects.filter(tenant=self.request.tenant)


def fee_lookup_api(request):
    """
    API endpoint to lookup fees for a procedure code.
    GET parameters:
        - procedure_code: CPT/HCPCS code
        - modifier: Optional modifier (26, TC, etc.)
        - schedule_type: Optional filter by schedule type
        - payer_id: Optional specific payer
    """
    procedure_code = request.GET.get("procedure_code")
    modifier = request.GET.get("modifier", "").strip()
    schedule_type = request.GET.get("schedule_type")
    payer_id = request.GET.get("payer_id")

    if not procedure_code:
        return JsonResponse({"error": "procedure_code is required"}, status=400)

    # Build query
    queryset = (
        FeeScheduleItem.objects.filter(
            tenant=request.tenant,
            procedure_code=procedure_code,
            fee_schedule__is_active=True,
            fee_schedule__effective_date__lte=timezone.now().date(),
        )
        .exclude(fee_schedule__expiration_date__lt=timezone.now().date())
        .select_related("fee_schedule")
    )

    # Apply filters
    if schedule_type:
        queryset = queryset.filter(fee_schedule__schedule_type=schedule_type)

    if payer_id:
        queryset = queryset.filter(fee_schedule__payer_id=payer_id)

    # Order by priority: Contract > Medicare > Commercial > Self-Pay > Chargemaster
    priority_order = {
        "CONTRACT": 1,
        "MEDICARE": 2,
        "MEDICAID": 3,
        "COMMERCIAL": 4,
        "SELF_PAY": 5,
        "CHARGEMASTER": 6,
    }

    results = []
    for item in queryset:
        # Determine which fee to use based on modifier
        if modifier == "26":  # Professional component
            fee = item.professional_component
        elif modifier == "TC":  # Technical component
            fee = item.technical_component
        else:  # Global or no modifier
            fee = item.global_fee or item.professional_component + item.technical_component

        results.append(
            {
                "id": str(item.id),
                "procedure_code": item.procedure_code,
                "procedure_description": item.procedure_description,
                "fee_schedule_name": item.fee_schedule.name,
                "fee_schedule_type": item.fee_schedule.schedule_type,
                "payer_name": item.fee_schedule.payer.name
                if item.fee_schedule.payer
                else None,
                "professional_component": str(item.professional_component),
                "technical_component": str(item.technical_component),
                "global_fee": str(item.global_fee) if item.global_fee else None,
                "calculated_fee": str(fee),
                "effective_date": str(item.fee_schedule.effective_date),
                "expiration_date": str(item.fee_schedule.expiration_date)
                if item.fee_schedule.expiration_date
                else None,
            }
        )

    return JsonResponse({"results": results, "count": len(results)})


def fee_calculate_api(request):
    """
    API endpoint to calculate total fees for multiple procedure codes.
    POST JSON:
        {
            "items": [
                {"procedure_code": "71045", "modifier": "26", "units": 1},
                {"procedure_code": "71046", "modifier": "", "units": 2}
            ],
            "schedule_type": "MEDICARE",  // Optional
            "payer_id": "uuid"  // Optional
        }
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    try:
        data = json.loads(request.body)
        items = data.get("items", [])
        schedule_type = data.get("schedule_type")
        payer_id = data.get("payer_id")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not items:
        return JsonResponse({"error": "No items provided"}, status=400)

    total_charges = Decimal("0.00")
    line_items = []

    for item_data in items:
        procedure_code = item_data.get("procedure_code")
        modifier = item_data.get("modifier", "").strip()
        units = Decimal(str(item_data.get("units", 1)))

        if not procedure_code:
            continue

        # Lookup fee
        queryset = FeeScheduleItem.objects.filter(
            tenant=request.tenant,
            procedure_code=procedure_code,
            fee_schedule__is_active=True,
            fee_schedule__effective_date__lte=timezone.now().date(),
        ).exclude(fee_schedule__expiration_date__lt=timezone.now().date())

        if schedule_type:
            queryset = queryset.filter(fee_schedule__schedule_type=schedule_type)

        if payer_id:
            queryset = queryset.filter(fee_schedule__payer_id=payer_id)

        # Get first matching item (highest priority)
        fee_item = queryset.first()

        if fee_item:
            # Calculate fee based on modifier
            if modifier == "26":
                unit_fee = fee_item.professional_component
            elif modifier == "TC":
                unit_fee = fee_item.technical_component
            else:
                unit_fee = fee_item.global_fee or (
                    fee_item.professional_component + fee_item.technical_component
                )

            line_total = unit_fee * units
            total_charges += line_total

            line_items.append(
                {
                    "procedure_code": procedure_code,
                    "modifier": modifier,
                    "units": str(units),
                    "unit_fee": str(unit_fee),
                    "line_total": str(line_total),
                    "fee_schedule": fee_item.fee_schedule.name,
                }
            )
        else:
            line_items.append(
                {
                    "procedure_code": procedure_code,
                    "modifier": modifier,
                    "units": str(units),
                    "unit_fee": "0.00",
                    "line_total": "0.00",
                    "error": "No fee schedule found for this procedure",
                }
            )

    return JsonResponse(
        {
            "line_items": line_items,
            "total_charges": str(total_charges),
            "currency": "USD",
            "calculated_at": timezone.now().isoformat(),
        }
    )


# ============================================================================
# INSURANCE PAYER VIEWS
# ============================================================================


class InsurancePayerListView(LoginRequiredMixin, ListView):
    """List all insurance payers with filtering and search"""

    model = InsurancePayer
    template_name = "billing/payer_list.html"
    context_object_name = "payers"
    paginate_by = 25

    def get_queryset(self):
        queryset = InsurancePayer.objects.filter(tenant=self.request.tenant)

        # Filter by status
        status = self.request.GET.get("status")
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)

        # Filter by type
        payer_type = self.request.GET.get("payer_type")
        if payer_type:
            queryset = queryset.filter(payer_type=payer_type)

        # Search by name or payer_id
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(payer_id__icontains=search)
                | Q(short_name__icontains=search)
            )

        return queryset.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant

        context["total_payers"] = InsurancePayer.objects.filter(tenant=tenant).count()
        context["active_count"] = InsurancePayer.objects.filter(
            tenant=tenant, is_active=True
        ).count()
        context["commercial_count"] = InsurancePayer.objects.filter(
            tenant=tenant, payer_type="COMMERCIAL"
        ).count()
        context["government_count"] = InsurancePayer.objects.filter(
            tenant=tenant, payer_type__in=["MEDICARE", "MEDICAID", "TRICARE", "CHAMPVA"]
        ).count()
        return context


class InsurancePayerDetailView(LoginRequiredMixin, DetailView):
    """Detail view of an insurance payer"""

    model = InsurancePayer
    template_name = "billing/payer_detail.html"
    context_object_name = "payer"

    def get_queryset(self):
        return InsurancePayer.objects.filter(tenant=self.request.tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payer = self.object

        # Get related data
        context["insurance_count"] = PatientInsurance.objects.filter(
            tenant=self.request.tenant, payer=payer
        ).count()
        context["fee_schedules"] = FeeSchedule.objects.filter(
            tenant=self.request.tenant, payer=payer
        )

        return context


class InsurancePayerCreateView(LoginRequiredMixin, CreateView):
    """Create a new insurance payer"""

    model = InsurancePayer
    form_class = InsurancePayerForm
    template_name = "billing/payer_form.html"
    success_url = reverse_lazy("billing:payer_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["tenant"] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        return super().form_valid(form)


class InsurancePayerUpdateView(LoginRequiredMixin, UpdateView):
    """Update an insurance payer"""

    model = InsurancePayer
    form_class = InsurancePayerForm
    template_name = "billing/payer_form.html"
    success_url = reverse_lazy("billing:payer_list")

    def get_queryset(self):
        return InsurancePayer.objects.filter(tenant=self.request.tenant)


class InsurancePayerDeleteView(LoginRequiredMixin, DeleteView):
    """Delete an insurance payer (soft delete)"""

    model = InsurancePayer
    template_name = "billing/payer_confirm_delete.html"
    success_url = reverse_lazy("billing:payer_list")

    def get_queryset(self):
        return InsurancePayer.objects.filter(tenant=self.request.tenant)

    def delete(self, request, *args, **kwargs):
        payer = self.get_object()
        payer.is_active = False
        payer.save()
        return redirect(self.success_url)


# ============================================================================
# CLEARINGHOUSE VIEWS
# ============================================================================


class ClearinghouseListView(LoginRequiredMixin, ListView):
    """List all clearinghouses"""

    model = Clearinghouse
    template_name = "billing/clearinghouse_list.html"
    context_object_name = "clearinghouses"

    def get_queryset(self):
        return Clearinghouse.objects.filter(tenant=self.request.tenant).order_by("name")


class ClearinghouseDetailView(LoginRequiredMixin, DetailView):
    """Detail view of a clearinghouse"""

    model = Clearinghouse
    template_name = "billing/clearinghouse_detail.html"
    context_object_name = "clearinghouse"

    def get_queryset(self):
        return Clearinghouse.objects.filter(tenant=self.request.tenant)


class ClearinghouseCreateView(LoginRequiredMixin, CreateView):
    """Create a new clearinghouse"""

    model = Clearinghouse
    form_class = ClearinghouseForm
    template_name = "billing/clearinghouse_form.html"
    success_url = reverse_lazy("billing:clearinghouse_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["tenant"] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        return super().form_valid(form)


class ClearinghouseUpdateView(LoginRequiredMixin, UpdateView):
    """Update a clearinghouse"""

    model = Clearinghouse
    form_class = ClearinghouseForm
    template_name = "billing/clearinghouse_form.html"
    success_url = reverse_lazy("billing:clearinghouse_list")

    def get_queryset(self):
        return Clearinghouse.objects.filter(tenant=self.request.tenant)


# ============================================================================
# PATIENT INSURANCE VIEWS
# ============================================================================


class PatientInsuranceCreateView(LoginRequiredMixin, CreateView):
    """Add insurance to a patient"""

    model = PatientInsurance
    form_class = PatientInsuranceForm
    template_name = "billing/patient_insurance_form.html"

    def get_success_url(self):
        return reverse_lazy(
            "patients:patient_detail", kwargs={"pk": self.object.patient.pk}
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["tenant"] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        return super().form_valid(form)


class PatientInsuranceUpdateView(LoginRequiredMixin, UpdateView):
    """Update patient insurance"""

    model = PatientInsurance
    form_class = PatientInsuranceForm
    template_name = "billing/patient_insurance_form.html"

    def get_success_url(self):
        return reverse_lazy(
            "patients:patient_detail", kwargs={"pk": self.object.patient.pk}
        )

    def get_queryset(self):
        return PatientInsurance.objects.filter(tenant=self.request.tenant)


# ============================================================================
# AUTHORIZATION VIEWS
# ============================================================================


class AuthorizationCreateView(LoginRequiredMixin, CreateView):
    """Create a new authorization"""

    model = Authorization
    form_class = AuthorizationForm
    template_name = "billing/authorization_form.html"

    def get_success_url(self):
        return reverse_lazy(
            "orders:exam_detail", kwargs={"pk": self.object.exam_order.pk}
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["tenant"] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        return super().form_valid(form)


class AuthorizationUpdateView(LoginRequiredMixin, UpdateView):
    """Update an authorization"""

    model = Authorization
    form_class = AuthorizationForm
    template_name = "billing/authorization_form.html"

    def get_success_url(self):
        return reverse_lazy(
            "orders:exam_detail", kwargs={"pk": self.object.exam_order.pk}
        )

    def get_queryset(self):
        return Authorization.objects.filter(tenant=self.request.tenant)


# ============================================================================
# PATIENT ACCOUNT VIEWS
# ============================================================================


class PatientAccountDetailView(LoginRequiredMixin, DetailView):
    """Detail view of a patient account"""

    model = PatientAccount
    template_name = "billing/patient_account_detail.html"
    context_object_name = "account"

    def get_queryset(self):
        return PatientAccount.objects.filter(tenant=self.request.tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        account = self.object

        # Get recent service lines
        context["recent_charges"] = account.service_lines.all()[:10]

        # Get payments
        context["recent_payments"] = Payment.objects.filter(
            tenant=self.request.tenant, patient_account=account
        ).order_by("-payment_date")[:10]

        return context


class PatientAccountCreateView(LoginRequiredMixin, CreateView):
    """Create a patient account"""

    model = PatientAccount
    form_class = PatientAccountForm
    template_name = "billing/patient_account_form.html"

    def get_success_url(self):
        return reverse_lazy(
            "billing:patient_account_detail", kwargs={"pk": self.object.pk}
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["tenant"] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        # Generate account number if not provided
        if not form.instance.account_number:
            import uuid

            form.instance.account_number = f"ACC-{uuid.uuid4().hex[:8].upper()}"
        return super().form_valid(form)


# ============================================================================
# SERVICE LINE VIEWS (CHARGE CAPTURE)
# ============================================================================

class ServiceLineListView(LoginRequiredMixin, ListView):
    """List all service lines with filtering and search"""
    
    model = ServiceLine
    template_name = "billing/service_line_list.html"
    context_object_name = "service_lines"
    paginate_by = 25
    
    def get_queryset(self):
        queryset = ServiceLine.objects.filter(tenant=self.request.tenant).select_related(
            'exam_order', 'patient_account', 'rendering_provider', 'claim'
        )
        
        # Filter by billing status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(billing_status=status)
        
        # Filter by date range
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            queryset = queryset.filter(service_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(service_date__lte=date_to)
        
        # Search by procedure code
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(procedure_code__icontains=search) |
                Q(procedure_name__icontains=search)
            )
        
        return queryset.order_by('-service_date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        
        context['total_lines'] = ServiceLine.objects.filter(tenant=tenant).count()
        context['pending_count'] = ServiceLine.objects.filter(tenant=tenant, billing_status='PENDING').count()
        context['ready_count'] = ServiceLine.objects.filter(tenant=tenant, billing_status='READY').count()
        context['billed_count'] = ServiceLine.objects.filter(tenant=tenant, billing_status='BILLED').count()
        context['denied_count'] = ServiceLine.objects.filter(tenant=tenant, billing_status='DENIED').count()
        
        return context


class ServiceLineDetailView(LoginRequiredMixin, DetailView):
    """Detail view of a service line item"""
    
    model = ServiceLine
    template_name = "billing/service_line_detail.html"
    context_object_name = "service_line"
    
    def get_queryset(self):
        return ServiceLine.objects.filter(tenant=self.request.tenant).select_related(
            'exam_order', 'patient_account', 'rendering_provider', 'facility', 'claim'
        )


class ServiceLineCreateView(LoginRequiredMixin, CreateView):
    """Create a new service line (charge capture)"""
    
    model = ServiceLine
    form_class = ServiceLineForm
    template_name = "billing/service_line_form.html"
    success_url = reverse_lazy('billing:service_line_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        return kwargs
    
    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        # Auto-calculate total charge if not provided
        if not form.instance.total_charge:
            form.instance.total_charge = form.instance.unit_price * form.instance.quantity
        return super().form_valid(form)


class ServiceLineUpdateView(LoginRequiredMixin, UpdateView):
    """Update a service line item"""
    
    model = ServiceLine
    form_class = ServiceLineForm
    template_name = "billing/service_line_form.html"
    success_url = reverse_lazy('billing:service_line_list')
    
    def get_queryset(self):
        return ServiceLine.objects.filter(tenant=self.request.tenant)
    
    def form_valid(self, form):
        # Auto-calculate total charge
        if form.cleaned_data.get('unit_price') and form.cleaned_data.get('quantity'):
            form.instance.total_charge = form.instance.unit_price * form.instance.quantity
        return super().form_valid(form)


class ServiceLineDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a service line item"""
    
    model = ServiceLine
    template_name = "billing/service_line_confirm_delete.html"
    success_url = reverse_lazy('billing:service_line_list')
    
    def get_queryset(self):
        return ServiceLine.objects.filter(tenant=self.request.tenant)


# ============================================================================
# CLAIM VIEWS
# ============================================================================

class ClaimListView(LoginRequiredMixin, ListView):
    """List all claims with filtering and search"""
    
    model = Claim
    template_name = "billing/claim_list.html"
    context_object_name = "claims"
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Claim.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account', 'payer'
        )
        
        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # Filter by claim type
        claim_type = self.request.GET.get('claim_type')
        if claim_type:
            queryset = queryset.filter(claim_type=claim_type)
        
        # Filter by date range
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            queryset = queryset.filter(date_of_service_from__gte=date_from)
        if date_to:
            queryset = queryset.filter(date_of_service_to__lte=date_to)
        
        # Search by claim number
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(claim_number__icontains=search) |
                Q(internal_claim_id__icontains=search)
            )
        
        return queryset.order_by('-date_of_service_from')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        
        context['total_claims'] = Claim.objects.filter(tenant=tenant).count()
        context['draft_count'] = Claim.objects.filter(tenant=tenant, status='DRAFT').count()
        context['submitted_count'] = Claim.objects.filter(tenant=tenant, status='SUBMITTED').count()
        context['accepted_count'] = Claim.objects.filter(tenant=tenant, status='ACCEPTED').count()
        context['paid_count'] = Claim.objects.filter(tenant=tenant, status='PAID').count()
        context['denied_count'] = Claim.objects.filter(tenant=tenant, status='DENIED').count()
        
        return context


class ClaimDetailView(LoginRequiredMixin, DetailView):
    """Detail view of a claim with all line items"""
    
    model = Claim
    template_name = "billing/claim_detail.html"
    context_object_name = "claim"
    
    def get_queryset(self):
        return Claim.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account', 'payer'
        ).prefetch_related('lines', 'service_lines')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.object
        
        context['line_count'] = claim.lines.count()
        context['total_charges'] = claim.lines.aggregate(total=Sum('charge_amount'))['total'] or Decimal('0.00')
        context['total_paid'] = claim.lines.aggregate(total=Sum('paid_amount'))['total'] or Decimal('0.00')
        context['total_adjustments'] = claim.lines.aggregate(total=Sum('adjustment_amount'))['total'] or Decimal('0.00')
        
        return context


class ClaimCreateView(LoginRequiredMixin, CreateView):
    """Create a new insurance claim"""
    
    model = Claim
    form_class = ClaimForm
    template_name = "billing/claim_form.html"
    success_url = reverse_lazy('billing:claim_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        return kwargs
    
    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        # Generate claim number if not provided
        if not form.instance.claim_number:
            import uuid
            form.instance.claim_number = f"CLM-{uuid.uuid4().hex[:10].upper()}"
        if not form.instance.internal_claim_id:
            import uuid
            form.instance.internal_claim_id = f"INT-{uuid.uuid4().hex[:10].upper()}"
        return super().form_valid(form)


class ClaimUpdateView(LoginRequiredMixin, UpdateView):
    """Update a claim"""
    
    model = Claim
    form_class = ClaimForm
    template_name = "billing/claim_form.html"
    success_url = reverse_lazy('billing:claim_list')
    
    def get_queryset(self):
        return Claim.objects.filter(tenant=self.request.tenant)


class ClaimDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a claim (only drafts can be deleted)"""
    
    model = Claim
    template_name = "billing/claim_confirm_delete.html"
    success_url = reverse_lazy('billing:claim_list')
    
    def get_queryset(self):
        return Claim.objects.filter(tenant=self.request.tenant)
    
    def delete(self, request, *args, **kwargs):
        claim = self.get_object()
        if claim.status != 'DRAFT':
            # Only draft claims can be deleted
            return render(request, 'billing/claim_error.html', {
                'message': 'Only draft claims can be deleted.'
            })
        return super().delete(request, *args, **kwargs)


# ============================================================================
# CLAIM LINE VIEWS
# ============================================================================

class ClaimLineCreateView(LoginRequiredMixin, CreateView):
    """Add a line item to a claim"""
    
    model = ClaimLine
    form_class = ClaimLineForm
    template_name = "billing/claim_line_form.html"
    
    def get_success_url(self):
        return reverse_lazy('billing:claim_detail', kwargs={'pk': self.kwargs['claim_pk']})
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        return kwargs
    
    def form_valid(self, form):
        claim = get_object_or_404(Claim.objects.filter(tenant=self.request.tenant), pk=self.kwargs['claim_pk'])
        form.instance.claim = claim
        
        # Auto-set line number
        last_line = ClaimLine.objects.filter(claim=claim).order_by('-line_number').first()
        form.instance.line_number = (last_line.line_number + 1) if last_line else 1
        
        return super().form_valid(form)


class ClaimLineUpdateView(LoginRequiredMixin, UpdateView):
    """Update a claim line item"""
    
    model = ClaimLine
    form_class = ClaimLineForm
    template_name = "billing/claim_line_form.html"
    
    def get_success_url(self):
        return reverse_lazy('billing:claim_detail', kwargs={'pk': self.object.claim.pk})
    
    def get_queryset(self):
        return ClaimLine.objects.filter(claim__tenant=self.request.tenant)


class ClaimLineDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a claim line item"""
    
    model = ClaimLine
    template_name = "billing/claim_line_confirm_delete.html"
    
    def get_success_url(self):
        return reverse_lazy('billing:claim_detail', kwargs={'pk': self.object.claim.pk})
    
    def get_queryset(self):
        return ClaimLine.objects.filter(claim__tenant=self.request.tenant)


# ============================================================================
# PAYMENT POSTING VIEWS
# ============================================================================

class PaymentPostingListView(LoginRequiredMixin, ListView):
    """List all payment postings"""

    model = PaymentPosting
    template_name = "billing/payment_posting_list.html"
    context_object_name = "payment_postings"
    paginate_by = 25

    def get_queryset(self):
        queryset = PaymentPosting.objects.filter(tenant=self.request.tenant).select_related(
            'claim', 'payer', 'posted_by'
        ).order_by('-posting_date')
        
        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # Filter by payment method
        payment_method = self.request.GET.get('payment_method')
        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)
        
        # Search by check number or ERA trace
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(check_number__icontains=search) |
                Q(era_trace_number__icontains=search)
            )
        
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = ['UNPOSTED', 'POSTED', 'REVERSED']
        context['payment_methods'] = ['ERA', 'CHECK', 'EFT', 'CASH', 'CREDIT_CARD']
        
        # Summary stats
        context['total_unposted'] = PaymentPosting.objects.filter(
            tenant=self.request.tenant, status='UNPOSTED'
        ).count()
        context['total_posted'] = PaymentPosting.objects.filter(
            tenant=self.request.tenant, status='POSTED'
        ).count()
        
        return context


class PaymentPostingDetailView(LoginRequiredMixin, DetailView):
    """View payment posting details with all payment details"""

    model = PaymentPosting
    template_name = "billing/payment_posting_detail.html"
    context_object_name = "payment_posting"

    def get_queryset(self):
        return PaymentPosting.objects.filter(tenant=self.request.tenant).select_related(
            'claim', 'payer'
        ).prefetch_related('details__claim_line')


class PaymentPostingCreateView(LoginRequiredMixin, CreateView):
    """Create a new payment posting (manual or from ERA)"""

    model = PaymentPosting
    form_class = PaymentPostingForm
    template_name = "billing/payment_posting_form.html"
    success_url = reverse_lazy('billing:payment_posting_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        kwargs['initial']['posting_date'] = timezone.now().date()
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        return super().form_valid(form)


class PaymentPostingUpdateView(LoginRequiredMixin, UpdateView):
    """Update a payment posting"""

    model = PaymentPosting
    form_class = PaymentPostingForm
    template_name = "billing/payment_posting_form.html"
    success_url = reverse_lazy('billing:payment_posting_list')

    def get_queryset(self):
        return PaymentPosting.objects.filter(tenant=self.request.tenant)


class PaymentPostingDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a payment posting (only unposted can be deleted)"""

    model = PaymentPosting
    template_name = "billing/payment_posting_confirm_delete.html"
    success_url = reverse_lazy('billing:payment_posting_list')

    def get_queryset(self):
        return PaymentPosting.objects.filter(tenant=self.request.tenant)

    def delete(self, request, *args, **kwargs):
        posting = self.get_object()
        if posting.status == 'POSTED':
            return render(request, 'billing/payment_posting_error.html', {
                'message': 'Posted payment postings cannot be deleted. Please reverse instead.'
            })
        return super().delete(request, *args, **kwargs)


# ============================================================================
# PAYMENT DETAIL VIEWS
# ============================================================================

class PaymentDetailCreateView(LoginRequiredMixin, CreateView):
    """Add a payment detail to a payment posting"""

    model = PaymentDetail
    form_class = PaymentDetailForm
    template_name = "billing/payment_detail_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_posting_detail', kwargs={'pk': self.kwargs['posting_pk']})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        posting = get_object_or_404(
            PaymentPosting.objects.filter(tenant=self.request.tenant),
            pk=self.kwargs['posting_pk']
        )
        form.instance.payment_posting = posting
        return super().form_valid(form)


class PaymentDetailUpdateView(LoginRequiredMixin, UpdateView):
    """Update a payment detail"""

    model = PaymentDetail
    form_class = PaymentDetailForm
    template_name = "billing/payment_detail_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_posting_detail', kwargs={'pk': self.object.payment_posting.pk})

    def get_queryset(self):
        return PaymentDetail.objects.filter(payment_posting__tenant=self.request.tenant)


class PaymentDetailDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a payment detail"""

    model = PaymentDetail
    template_name = "billing/payment_detail_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_posting_detail', kwargs={'pk': self.object.payment_posting.pk})

    def get_queryset(self):
        return PaymentDetail.objects.filter(payment_posting__tenant=self.request.tenant)


# ============================================================================
# PATIENT PAYMENT VIEWS
# ============================================================================

class PaymentListView(LoginRequiredMixin, ListView):
    """List all patient payments"""

    model = Payment
    template_name = "billing/payment_list.html"
    context_object_name = "payments"
    paginate_by = 25

    def get_queryset(self):
        queryset = Payment.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account', 'received_by'
        ).order_by('-payment_date')
        
        # Filter by payment method
        payment_method = self.request.GET.get('payment_method')
        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)
        
        # Search by check number or transaction ID
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(check_number__icontains=search) |
                Q(transaction_id__icontains=search)
            )
        
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payment_methods'] = ['CASH', 'CHECK', 'CREDIT_CARD', 'DEBIT_CARD', 'EFT', 'ONLINE', 'PAYMENT_PLAN']
        
        # Summary stats
        today = timezone.now().date()
        context['today_total'] = Payment.objects.filter(
            tenant=self.request.tenant, payment_date__date=today
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        return context


class PaymentDetailView(LoginRequiredMixin, DetailView):
    """View payment details with allocations"""

    model = Payment
    template_name = "billing/payment_detail.html"
    context_object_name = "payment"

    def get_queryset(self):
        return Payment.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account'
        ).prefetch_related('allocations__service_line')


class PaymentCreateView(LoginRequiredMixin, CreateView):
    """Create a new patient payment"""

    model = Payment
    form_class = PaymentForm
    template_name = "billing/payment_form.html"
    success_url = reverse_lazy('billing:payment_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        kwargs['initial']['payment_date'] = timezone.now()
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        form.instance.received_by = self.request.user
        return super().form_valid(form)


class PaymentUpdateView(LoginRequiredMixin, UpdateView):
    """Update a patient payment"""

    model = Payment
    form_class = PaymentForm
    template_name = "billing/payment_form.html"
    success_url = reverse_lazy('billing:payment_list')

    def get_queryset(self):
        return Payment.objects.filter(tenant=self.request.tenant)


class PaymentDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a patient payment"""

    model = Payment
    template_name = "billing/payment_confirm_delete.html"
    success_url = reverse_lazy('billing:payment_list')

    def get_queryset(self):
        return Payment.objects.filter(tenant=self.request.tenant)


# ============================================================================
# PAYMENT ALLOCATION VIEWS
# ============================================================================

class PaymentAllocationCreateView(LoginRequiredMixin, CreateView):
    """Allocate a payment to a service line"""

    model = PaymentAllocation
    form_class = PaymentAllocationForm
    template_name = "billing/payment_allocation_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_detail', kwargs={'pk': self.kwargs['payment_pk']})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        payment = get_object_or_404(
            Payment.objects.filter(tenant=self.request.tenant),
            pk=self.kwargs['payment_pk']
        )
        form.instance.payment = payment
        return super().form_valid(form)


class PaymentAllocationUpdateView(LoginRequiredMixin, UpdateView):
    """Update a payment allocation"""

    model = PaymentAllocation
    form_class = PaymentAllocationForm
    template_name = "billing/payment_allocation_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_detail', kwargs={'pk': self.object.payment.pk})

    def get_queryset(self):
        return PaymentAllocation.objects.filter(payment__tenant=self.request.tenant)


class PaymentAllocationDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a payment allocation"""

    model = PaymentAllocation
    template_name = "billing/payment_allocation_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_detail', kwargs={'pk': self.object.payment.pk})

    def get_queryset(self):
        return PaymentAllocation.objects.filter(payment__tenant=self.request.tenant)


# ============================================================================
# PATIENT STATEMENT VIEWS
# ============================================================================

class PatientStatementListView(LoginRequiredMixin, ListView):
    """List all patient statements with filtering and search"""

    model = PatientStatement
    template_name = "billing/patient_statement_list.html"
    context_object_name = "statements"
    paginate_by = 25

    def get_queryset(self):
        queryset = PatientStatement.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account', 'patient_account__patient'
        )

        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        # Filter by delivery method
        delivery_method = self.request.GET.get('delivery_method')
        if delivery_method:
            queryset = queryset.filter(delivery_method=delivery_method)

        # Search by statement number or patient
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(statement_number__icontains=search) |
                models.Q(patient_account__patient__mrn__icontains=search) |
                models.Q(patient_account__patient__first_name__icontains=search) |
                models.Q(patient_account__patient__last_name__icontains=search)
            )

        # Date range filter
        date_from = self.request.GET.get('date_from')
        if date_from:
            queryset = queryset.filter(statement_date__gte=date_from)

        date_to = self.request.GET.get('date_to')
        if date_to:
            queryset = queryset.filter(statement_date__lte=date_to)

        return queryset.order_by('-statement_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_statements'] = PatientStatement.objects.filter(
            tenant=self.request.tenant
        ).count()
        context['draft_count'] = PatientStatement.objects.filter(
            tenant=self.request.tenant, status='DRAFT'
        ).count()
        context['sent_count'] = PatientStatement.objects.filter(
            tenant=self.request.tenant, status='SENT'
        ).count()
        context['overdue_count'] = PatientStatement.objects.filter(
            tenant=self.request.tenant, status='OVERDUE'
        ).count()
        context['total_balance'] = PatientStatement.objects.filter(
            tenant=self.request.tenant
        ).aggregate(total=models.Sum('current_balance'))['total'] or Decimal('0.00')
        return context


class PatientStatementDetailView(LoginRequiredMixin, DetailView):
    """View details of a patient statement"""

    model = PatientStatement
    template_name = "billing/patient_statement_detail.html"
    context_object_name = "statement"

    def get_queryset(self):
        return PatientStatement.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account', 'patient_account__patient'
        ).prefetch_related('patient_account__service_lines')


class PatientStatementCreateView(LoginRequiredMixin, CreateView):
    """Create a new patient billing statement"""

    model = PatientStatement
    form_class = PatientStatementForm
    template_name = "billing/patient_statement_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:statement_detail', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        # Generate unique statement number
        prefix = "STMT"
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        random_suffix = str(uuid.uuid4())[:6].upper()
        form.instance.statement_number = f"{prefix}-{timestamp}-{random_suffix}"
        return super().form_valid(form)


class PatientStatementUpdateView(LoginRequiredMixin, UpdateView):
    """Update a patient statement"""

    model = PatientStatement
    form_class = PatientStatementForm
    template_name = "billing/patient_statement_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:statement_detail', kwargs={'pk': self.object.pk})

    def get_queryset(self):
        return PatientStatement.objects.filter(tenant=self.request.tenant)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs


class PatientStatementDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a patient statement"""

    model = PatientStatement
    template_name = "billing/patient_statement_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy('billing:statement_list')

    def get_queryset(self):
        return PatientStatement.objects.filter(tenant=self.request.tenant)


# ============================================================================
# PAYMENT PLAN VIEWS
# ============================================================================

class PaymentPlanListView(LoginRequiredMixin, ListView):
    """List all payment plans with filtering and search"""

    model = PaymentPlan
    template_name = "billing/payment_plan_list.html"
    context_object_name = "payment_plans"
    paginate_by = 25

    def get_queryset(self):
        queryset = PaymentPlan.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account', 'patient_account__patient'
        )

        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        # Search by patient
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(patient_account__patient__mrn__icontains=search) |
                models.Q(patient_account__patient__first_name__icontains=search) |
                models.Q(patient_account__patient__last_name__icontains=search)
            )

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_plans'] = PaymentPlan.objects.filter(
            tenant=self.request.tenant
        ).count()
        context['active_count'] = PaymentPlan.objects.filter(
            tenant=self.request.tenant, status='ACTIVE'
        ).count()
        context['completed_count'] = PaymentPlan.objects.filter(
            tenant=self.request.tenant, status='COMPLETED'
        ).count()
        context['defaulted_count'] = PaymentPlan.objects.filter(
            tenant=self.request.tenant, status='DEFAULTED'
        ).count()
        context['total_remaining'] = PaymentPlan.objects.filter(
            tenant=self.request.tenant, status='ACTIVE'
        ).aggregate(total=models.Sum('remaining_balance'))['total'] or Decimal('0.00')
        return context


class PaymentPlanDetailView(LoginRequiredMixin, DetailView):
    """View details of a payment plan including installments"""

    model = PaymentPlan
    template_name = "billing/payment_plan_detail.html"
    context_object_name = "payment_plan"

    def get_queryset(self):
        return PaymentPlan.objects.filter(tenant=self.request.tenant).select_related(
            'patient_account', 'patient_account__patient'
        ).prefetch_related('installments', 'installments__payment')


class PaymentPlanCreateView(LoginRequiredMixin, CreateView):
    """Create a new payment plan for a patient"""

    model = PaymentPlan
    form_class = PaymentPlanForm
    template_name = "billing/payment_plan_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_plan_detail', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        response = super().form_valid(form)
        
        # Auto-generate installments after plan creation
        self._generate_installments(form.instance)
        
        # Update patient account to mark as having payment plan
        account = form.instance.patient_account
        account.has_payment_plan = True
        account.payment_plan_balance = form.instance.remaining_balance
        account.monthly_payment = form.instance.monthly_payment
        account.save()
        
        return response

    def _generate_installments(self, payment_plan):
        """Generate installment records based on plan terms"""
        from datetime import timedelta
        import calendar
        
        current_date = payment_plan.first_payment_date
        monthly_payment = payment_plan.monthly_payment
        remaining = payment_plan.total_amount
        
        for i in range(1, payment_plan.number_of_payments + 1):
            # Calculate amount for this installment (last one gets remainder)
            if i == payment_plan.number_of_payments:
                amount = remaining
            else:
                amount = min(monthly_payment, remaining)
            
            PaymentPlanInstallment.objects.create(
                payment_plan=payment_plan,
                installment_number=i,
                due_date=current_date,
                amount_due=amount,
                status='PENDING'
            )
            
            remaining -= amount
            
            # Move to next month, adjusting for day of month
            next_month = current_date.month + 1
            next_year = current_date.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            
            # Handle months with fewer days (e.g., Feb 30 -> Feb 28)
            day = min(payment_plan.payment_day, calendar.monthrange(next_year, next_month)[1])
            current_date = current_date.replace(year=next_year, month=next_month, day=day)


class PaymentPlanUpdateView(LoginRequiredMixin, UpdateView):
    """Update a payment plan"""

    model = PaymentPlan
    form_class = PaymentPlanForm
    template_name = "billing/payment_plan_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_plan_detail', kwargs={'pk': self.object.pk})

    def get_queryset(self):
        return PaymentPlan.objects.filter(tenant=self.request.tenant)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs


class PaymentPlanDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a payment plan"""

    model = PaymentPlan
    template_name = "billing/payment_plan_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_plan_list')

    def get_queryset(self):
        return PaymentPlan.objects.filter(tenant=self.request.tenant)

    def delete(self, request, *args, **kwargs):
        """Also update the patient account when deleting a plan"""
        self.object = self.get_object()
        account = self.object.patient_account
        account.has_payment_plan = False
        account.payment_plan_balance = None
        account.monthly_payment = None
        account.save()
        return super().delete(request, *args, **kwargs)


class PaymentPlanInstallmentUpdateView(LoginRequiredMixin, UpdateView):
    """Update a payment plan installment"""

    model = PaymentPlanInstallment
    form_class = PaymentPlanInstallmentForm
    template_name = "billing/payment_plan_installment_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:payment_plan_detail', kwargs={'pk': self.object.payment_plan.pk})

    def get_queryset(self):
        return PaymentPlanInstallment.objects.filter(
            payment_plan__tenant=self.request.tenant
        )

    def form_valid(self, form):
        response = super().form_valid(form)
        
        # Update payment plan stats if installment was paid
        if form.instance.status == 'PAID' and form.instance.payment:
            plan = form.instance.payment_plan
            plan.payments_made += 1
            plan.remaining_balance -= form.instance.amount_paid
            if plan.payments_made >= plan.number_of_payments:
                plan.status = 'COMPLETED'
            plan.save()
            
            # Update patient account
            account = plan.patient_account
            account.payment_plan_balance = plan.remaining_balance
            if plan.status == 'COMPLETED':
                account.has_payment_plan = False
                account.payment_plan_balance = None
                account.monthly_payment = None
            account.save()
        
        return response
from datetime import timedelta


# Denial Reason Views

class DenialReasonListView(LoginRequiredMixin, ListView):
    """List all denial reasons"""

    model = DenialReason
    template_name = "billing/denial_reason_list.html"
    context_object_name = "denial_reasons"

    def get_queryset(self):
        return DenialReason.objects.filter(tenant=self.request.tenant)


class DenialReasonDetailView(LoginRequiredMixin, DetailView):
    """View details of a denial reason"""

    model = DenialReason
    template_name = "billing/denial_reason_detail.html"
    context_object_name = "denial_reason"

    def get_queryset(self):
        return DenialReason.objects.filter(tenant=self.request.tenant)


class DenialReasonCreateView(LoginRequiredMixin, CreateView):
    """Create a new denial reason"""

    model = DenialReason
    form_class = DenialReasonForm
    template_name = "billing/denial_reason_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:denial_reason_list')

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        return super().form_valid(form)


class DenialReasonUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing denial reason"""

    model = DenialReason
    form_class = DenialReasonForm
    template_name = "billing/denial_reason_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:denial_reason_list')

    def get_queryset(self):
        return DenialReason.objects.filter(tenant=self.request.tenant)


class DenialReasonDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a denial reason"""

    model = DenialReason
    template_name = "billing/denial_reason_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy('billing:denial_reason_list')

    def get_queryset(self):
        return DenialReason.objects.filter(tenant=self.request.tenant)


# Claim Appeal Views

class ClaimAppealListView(LoginRequiredMixin, ListView):
    """List all claim appeals"""

    model = ClaimAppeal
    template_name = "billing/claim_appeal_list.html"
    context_object_name = "appeals"

    def get_queryset(self):
        return ClaimAppeal.objects.filter(claim__tenant=self.request.tenant).select_related('claim', 'claim_line')


class ClaimAppealDetailView(LoginRequiredMixin, DetailView):
    """View details of a claim appeal"""

    model = ClaimAppeal
    template_name = "billing/claim_appeal_detail.html"
    context_object_name = "appeal"

    def get_queryset(self):
        return ClaimAppeal.objects.filter(claim__tenant=self.request.tenant).select_related('claim', 'claim_line')


class ClaimAppealCreateView(LoginRequiredMixin, CreateView):
    """Create a new claim appeal"""

    model = ClaimAppeal
    form_class = ClaimAppealForm
    template_name = "billing/claim_appeal_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:claim_appeal_list')

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        # Auto-set filed_date if not provided
        if not form.instance.filed_date:
            form.instance.filed_date = timezone.now().date()
        # Auto-calculate due_date based on denial reason if not provided
        if not form.instance.due_date and form.instance.claim:
            denial_reason = form.instance.claim.denial_reason
            if denial_reason:
                form.instance.due_date = form.instance.filed_date + timedelta(days=denial_reason.appeal_deadline_days)
            else:
                form.instance.due_date = form.instance.filed_date + timedelta(days=30)
        return super().form_valid(form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs


class ClaimAppealUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing claim appeal"""

    model = ClaimAppeal
    form_class = ClaimAppealForm
    template_name = "billing/claim_appeal_form.html"

    def get_success_url(self):
        return reverse_lazy('billing:claim_appeal_detail', kwargs={'pk': self.object.pk})

    def get_queryset(self):
        return ClaimAppeal.objects.filter(claim__tenant=self.request.tenant)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs


class ClaimAppealDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a claim appeal"""

    model = ClaimAppeal
    template_name = "billing/claim_appeal_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy('billing:claim_appeal_list')

    def get_queryset(self):
        return ClaimAppeal.objects.filter(claim__tenant=self.request.tenant)


# ============================================================================
# EDI & CLEARINGHOUSE VIEWS
# ============================================================================

class ClaimGenerate837View(LoginRequiredMixin, View):
    """Generate 837 EDI file for a claim"""
    
    def get(self, request, claim_id):
        if not EDI_AVAILABLE:
            return JsonResponse({'error': 'EDI services not available'}, status=503)
        
        try:
            claim = get_object_or_404(Claim.objects.filter(tenant=request.tenant), id=claim_id)
            
            # Generate 837 content
            edi_content = generate_claim_837(claim_id)
            
            if not edi_content:
                return JsonResponse({'error': 'Failed to generate 837 file'}, status=400)
            
            # Return as downloadable file
            response = HttpResponse(edi_content, content_type='application/x12')
            response['Content-Disposition'] = f'attachment; filename="claim_{claim.claim_number}.837"'
            return response
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class ClaimSubmitToClearinghouseView(LoginRequiredMixin, View):
    """Submit claim to clearinghouse"""
    
    def post(self, request, claim_id):
        if not EDI_AVAILABLE:
            return JsonResponse({'error': 'EDI services not available'}, status=503)
        
        try:
            result = submit_claim_to_clearinghouse(claim_id)
            
            if result.get('success'):
                return JsonResponse({
                    'success': True,
                    'message': result.get('message', 'Claim submitted successfully'),
                    'transmission_id': result.get('transmission_id'),
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': result.get('error', 'Unknown error'),
                }, status=400)
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class ERAUploadView(LoginRequiredMixin, View):
    """Upload and process ERA file"""
    
    def get(self, request):
        return render(request, 'billing/era_upload.html')
    
    def post(self, request):
        if not EDI_AVAILABLE:
            return JsonResponse({'error': 'EDI services not available'}, status=503)
        
        try:
            era_file = request.FILES.get('era_file')
            
            if not era_file:
                return JsonResponse({'error': 'No file uploaded'}, status=400)
            
            # Read file content
            file_content = era_file.read().decode('utf-8')
            
            # Process ERA
            postings = process_era_file(file_content, request.tenant)
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully processed {len(postings)} payment posting(s)',
                'postings_count': len(postings),
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class ClaimStatusCheckView(LoginRequiredMixin, View):
    """Check claim status via clearinghouse (276/271)"""
    
    def get(self, request, claim_id):
        if not EDI_AVAILABLE:
            return JsonResponse({'error': 'EDI services not available'}, status=503)
        
        try:
            from .edi_services import ClearinghouseClient
            
            claim = get_object_or_404(Claim.objects.filter(tenant=request.tenant), id=claim_id)
            
            if not claim.payer or not claim.payer.clearinghouse:
                return JsonResponse({
                    'error': 'No clearinghouse configured for this claim\'s payer'
                }, status=400)
            
            client = ClearinghouseClient(claim.payer.clearinghouse)
            status_result = client.check_claim_status(claim.claim_number)
            
            if 'error' in status_result:
                return JsonResponse({'error': status_result['error']}, status=400)
            
            return JsonResponse(status_result)
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class FetchERAFilesView(LoginRequiredMixin, View):
    """Fetch ERA files from clearinghouse"""
    
    def get(self, request):
        if not EDI_AVAILABLE:
            return JsonResponse({'error': 'EDI services not available'}, status=503)
        
        try:
            from .edi_services import ClearinghouseClient
            
            # Get optional date range
            start_date_str = request.GET.get('start_date')
            end_date_str = request.GET.get('end_date')
            
            start_date = None
            end_date = None
            
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            
            # Get active clearinghouses
            clearinghouses = Clearinghouse.objects.filter(
                tenant=request.tenant,
                is_active=True
            )
            
            all_files = []
            
            for ch in clearinghouses:
                client = ClearinghouseClient(ch)
                files = client.fetch_era(start_date, end_date)
                all_files.extend(files)
            
            return JsonResponse({
                'success': True,
                'files_count': len(all_files),
                'message': f'Fetched {len(all_files)} ERA file(s)'
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


# =============================================================================
# REPORTING VIEWS
# =============================================================================

class ChargeCaptureReportView(LoginRequiredMixin, View):
    """Daily Charge Capture Report"""
    
    def get(self, request):
        from .reporting_service import ReportingService
        
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        if not start_date_str:
            start_date = timezone.now().date() - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        if not end_date_str:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        service = ReportingService(request.tenant)
        data = service.get_charge_capture_report(start_date, end_date)
        
        context = {
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            'title': 'Charge Capture Report'
        }
        return render(request, 'billing/reports/charge_capture_report.html', context)


class ClaimSubmissionReportView(LoginRequiredMixin, View):
    """Claim Submission Report"""
    
    def get(self, request):
        from .reporting_service import ReportingService
        
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        if not start_date_str:
            start_date = timezone.now().date() - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        if not end_date_str:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        service = ReportingService(request.tenant)
        data = service.get_claim_submission_report(start_date, end_date)
        
        context = {
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            'title': 'Claim Submission Report'
        }
        return render(request, 'billing/reports/claim_submission_report.html', context)


class PaymentPostingReportView(LoginRequiredMixin, View):
    """Payment Posting Report"""
    
    def get(self, request):
        from .reporting_service import ReportingService
        
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        if not start_date_str:
            start_date = timezone.now().date() - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        if not end_date_str:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        service = ReportingService(request.tenant)
        data = service.get_payment_posting_report(start_date, end_date)
        
        context = {
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            'title': 'Payment Posting Report'
        }
        return render(request, 'billing/reports/payment_posting_report.html', context)


class ARAgingReportView(LoginRequiredMixin, View):
    """Accounts Receivable Aging Report"""
    
    def get(self, request):
        from .reporting_service import ReportingService
        
        as_of_date_str = request.GET.get('as_of_date')
        
        if not as_of_date_str:
            as_of_date = timezone.now().date()
        else:
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
        
        service = ReportingService(request.tenant)
        data = service.get_ar_aging_report(as_of_date)
        
        context = {
            'data': data,
            'as_of_date': as_of_date,
            'title': 'A/R Aging Report'
        }
        return render(request, 'billing/reports/ar_aging_report.html', context)


class DenialManagementReportView(LoginRequiredMixin, View):
    """Denial Management Report"""
    
    def get(self, request):
        from .reporting_service import ReportingService
        
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        if not start_date_str:
            start_date = timezone.now().date() - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        if not end_date_str:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        service = ReportingService(request.tenant)
        data = service.get_denial_management_report(start_date, end_date)
        
        context = {
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            'title': 'Denial Management Report'
        }
        return render(request, 'billing/reports/denial_management_report.html', context)


class RevenueAnalysisReportView(LoginRequiredMixin, View):
    """Revenue Analysis Report"""
    
    def get(self, request):
        from .reporting_service import ReportingService
        
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        if not start_date_str:
            start_date = timezone.now().date() - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        if not end_date_str:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        service = ReportingService(request.tenant)
        data = service.get_revenue_analysis_report(start_date, end_date)
        
        context = {
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            'title': 'Revenue Analysis Report'
        }
        return render(request, 'billing/reports/revenue_analysis_report.html', context)


class CollectionMetricsReportView(LoginRequiredMixin, View):
    """Collection Metrics Dashboard"""
    
    def get(self, request):
        from .reporting_service import ReportingService
        
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        if not start_date_str:
            start_date = timezone.now().date() - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        if not end_date_str:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        service = ReportingService(request.tenant)
        data = service.get_collection_metrics_report(start_date, end_date)
        
        context = {
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            'title': 'Collection Metrics'
        }
        return render(request, 'billing/reports/collection_metrics_report.html', context)
