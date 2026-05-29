import json
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum, Count
from django.urls import reverse_lazy
from django.utils import timezone
from .models import FeeSchedule, FeeScheduleItem
from .forms import FeeScheduleForm, FeeScheduleItemForm, FeeScheduleItemFormSet
from tenants.middleware import tenant_helper


class FeeScheduleListView(LoginRequiredMixin, ListView):
    """List all fee schedules with filtering and search"""
    model = FeeSchedule
    template_name = 'billing/fee_schedule_list.html'
    context_object_name = 'fee_schedules'
    paginate_by = 25
    
    def get_queryset(self):
        queryset = FeeSchedule.objects.filter(tenant=self.request.tenant)
        
        # Filter by status
        status = self.request.GET.get('status')
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'expired':
            queryset = queryset.filter(
                Q(expiration_date__lt=timezone.now().date()) | 
                Q(effective_date__gt=timezone.now().date())
            )
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)
        
        # Filter by type
        schedule_type = self.request.GET.get('schedule_type')
        if schedule_type:
            queryset = queryset.filter(schedule_type=schedule_type)
        
        # Search by name or code
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(description__icontains=search)
            )
        
        return queryset.select_related('payer').order_by('-effective_date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_count'] = FeeSchedule.objects.filter(
            tenant=self.request.tenant, is_active=True
        ).count()
        context['total_schedules'] = FeeSchedule.objects.filter(
            tenant=self.request.tenant
        ).count()
        return context


class FeeScheduleDetailView(LoginRequiredMixin, DetailView):
    """Detail view of a fee schedule with all items"""
    model = FeeSchedule
    template_name = 'billing/fee_schedule_detail.html'
    context_object_name = 'fee_schedule'
    
    def get_queryset(self):
        return FeeSchedule.objects.filter(tenant=self.request.tenant)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fee_schedule = self.object
        
        # Get statistics
        context['item_count'] = fee_schedule.items.count()
        context['professional_avg'] = fee_schedule.items.aggregate(
            avg=Sum('professional_fee') / Count('id')
        )['avg'] or Decimal('0.00')
        context['technical_avg'] = fee_schedule.items.aggregate(
            avg=Sum('technical_fee') / Count('id')
        )['avg'] or Decimal('0.00')
        context['global_avg'] = fee_schedule.items.aggregate(
            avg=Sum('global_fee') / Count('id')
        )['avg'] or Decimal('0.00')
        
        # Check if active
        today = timezone.now().date()
        context['is_currently_active'] = (
            fee_schedule.is_active and
            fee_schedule.effective_date <= today and
            (fee_schedule.expiration_date is None or fee_schedule.expiration_date >= today)
        )
        
        return context


class FeeScheduleCreateView(LoginRequiredMixin, CreateView):
    """Create a new fee schedule with items"""
    model = FeeSchedule
    form_class = FeeScheduleForm
    template_name = 'billing/fee_schedule_form.html'
    success_url = reverse_lazy('billing:fee_schedule_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        return kwargs
    
    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class FeeScheduleUpdateView(LoginRequiredMixin, UpdateView):
    """Update fee schedule header information"""
    model = FeeSchedule
    form_class = FeeScheduleForm
    template_name = 'billing/fee_schedule_form.html'
    success_url = reverse_lazy('billing:fee_schedule_list')
    
    def get_queryset(self):
        return FeeSchedule.objects.filter(tenant=self.request.tenant)
    
    def form_valid(self, form):
        form.instance.modified_by = self.request.user
        return super().form_valid(form)


class FeeScheduleDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a fee schedule (soft delete by setting inactive)"""
    model = FeeSchedule
    template_name = 'billing/fee_schedule_confirm_delete.html'
    success_url = reverse_lazy('billing:fee_schedule_list')
    
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
    template_name = 'billing/fee_schedule_item_form.html'
    
    def get_success_url(self):
        return reverse_lazy('billing:fee_schedule_detail', kwargs={'pk': self.kwargs['pk']})
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['tenant'] = self.request.tenant
        return kwargs
    
    def form_valid(self, form):
        fee_schedule = get_object_or_404(
            FeeSchedule.objects.filter(tenant=self.request.tenant),
            pk=self.kwargs['pk']
        )
        form.instance.fee_schedule = fee_schedule
        form.instance.tenant = self.request.tenant
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class FeeScheduleItemUpdateView(LoginRequiredMixin, UpdateView):
    """Update a fee schedule item"""
    model = FeeScheduleItem
    form_class = FeeScheduleItemForm
    template_name = 'billing/fee_schedule_item_form.html'
    
    def get_success_url(self):
        return reverse_lazy('billing:fee_schedule_detail', kwargs={'pk': self.object.fee_schedule.pk})
    
    def get_queryset(self):
        return FeeScheduleItem.objects.filter(tenant=self.request.tenant)
    
    def form_valid(self, form):
        form.instance.modified_by = self.request.user
        return super().form_valid(form)


class FeeScheduleItemDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a fee schedule item"""
    model = FeeScheduleItem
    template_name = 'billing/fee_schedule_item_confirm_delete.html'
    
    def get_success_url(self):
        return reverse_lazy('billing:fee_schedule_detail', kwargs={'pk': self.object.fee_schedule.pk})
    
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
    procedure_code = request.GET.get('procedure_code')
    modifier = request.GET.get('modifier', '').strip()
    schedule_type = request.GET.get('schedule_type')
    payer_id = request.GET.get('payer_id')
    
    if not procedure_code:
        return JsonResponse({'error': 'procedure_code is required'}, status=400)
    
    # Build query
    queryset = FeeScheduleItem.objects.filter(
        tenant=request.tenant,
        procedure_code=procedure_code,
        fee_schedule__is_active=True,
        fee_schedule__effective_date__lte=timezone.now().date()
    ).exclude(
        fee_schedule__expiration_date__lt=timezone.now().date()
    ).select_related('fee_schedule')
    
    # Apply filters
    if schedule_type:
        queryset = queryset.filter(fee_schedule__schedule_type=schedule_type)
    
    if payer_id:
        queryset = queryset.filter(fee_schedule__payer_id=payer_id)
    
    # Order by priority: Contract > Medicare > Commercial > Self-Pay > Chargemaster
    priority_order = {
        'CONTRACT': 1,
        'MEDICARE': 2,
        'MEDICAID': 3,
        'COMMERCIAL': 4,
        'SELF_PAY': 5,
        'CHARGEMASTER': 6,
    }
    
    results = []
    for item in queryset:
        # Determine which fee to use based on modifier
        if modifier == '26':  # Professional component
            fee = item.professional_fee
        elif modifier == 'TC':  # Technical component
            fee = item.technical_fee
        else:  # Global or no modifier
            fee = item.global_fee or item.professional_fee + item.technical_fee
        
        results.append({
            'id': str(item.id),
            'procedure_code': item.procedure_code,
            'procedure_name': item.procedure_name,
            'modifier': item.modifier,
            'fee_schedule_name': item.fee_schedule.name,
            'fee_schedule_type': item.fee_schedule.schedule_type,
            'payer_name': item.fee_schedule.payer.name if item.fee_schedule.payer else None,
            'professional_fee': str(item.professional_fee),
            'technical_fee': str(item.technical_fee),
            'global_fee': str(item.global_fee) if item.global_fee else None,
            'calculated_fee': str(fee),
            'unit_of_service': item.unit_of_service,
            'effective_date': str(item.fee_schedule.effective_date),
            'expiration_date': str(item.fee_schedule.expiration_date) if item.fee_schedule.expiration_date else None,
        })
    
    return JsonResponse({'results': results, 'count': len(results)})


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
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        schedule_type = data.get('schedule_type')
        payer_id = data.get('payer_id')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    if not items:
        return JsonResponse({'error': 'No items provided'}, status=400)
    
    total_charges = Decimal('0.00')
    line_items = []
    
    for item_data in items:
        procedure_code = item_data.get('procedure_code')
        modifier = item_data.get('modifier', '').strip()
        units = Decimal(str(item_data.get('units', 1)))
        
        if not procedure_code:
            continue
        
        # Lookup fee
        queryset = FeeScheduleItem.objects.filter(
            tenant=request.tenant,
            procedure_code=procedure_code,
            fee_schedule__is_active=True,
            fee_schedule__effective_date__lte=timezone.now().date()
        ).exclude(
            fee_schedule__expiration_date__lt=timezone.now().date()
        )
        
        if schedule_type:
            queryset = queryset.filter(fee_schedule__schedule_type=schedule_type)
        
        if payer_id:
            queryset = queryset.filter(fee_schedule__payer_id=payer_id)
        
        # Get first matching item (highest priority)
        fee_item = queryset.first()
        
        if fee_item:
            # Calculate fee based on modifier
            if modifier == '26':
                unit_fee = fee_item.professional_fee
            elif modifier == 'TC':
                unit_fee = fee_item.technical_fee
            else:
                unit_fee = fee_item.global_fee or (fee_item.professional_fee + fee_item.technical_fee)
            
            line_total = unit_fee * units
            total_charges += line_total
            
            line_items.append({
                'procedure_code': procedure_code,
                'modifier': modifier,
                'units': str(units),
                'unit_fee': str(unit_fee),
                'line_total': str(line_total),
                'fee_schedule': fee_item.fee_schedule.name,
            })
        else:
            line_items.append({
                'procedure_code': procedure_code,
                'modifier': modifier,
                'units': str(units),
                'unit_fee': '0.00',
                'line_total': '0.00',
                'error': 'No fee schedule found for this procedure',
            })
    
    return JsonResponse({
        'line_items': line_items,
        'total_charges': str(total_charges),
        'currency': 'USD',
        'calculated_at': timezone.now().isoformat(),
    })
