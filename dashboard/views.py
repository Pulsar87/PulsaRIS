from django.db.models import Count, Sum, Q, Avg
from django.db.models.functions import TruncDay, TruncMonth
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import timedelta, datetime

# Import models from all apps
from patients.models import Patient
from orders.models import ExamOrder, Procedure
from reports.models import Report
from billing.models import (
    InsurancePayer, Claim, ServiceLine, Payment,
    PatientAccount, FeeSchedule
)
from core.models import Facility, Device, Modality


def dashboard_stats(request):
    """Main dashboard view with stats and charts."""
    context = get_dashboard_context()
    return render(request, 'dashboard/stats.html', context)


def get_dashboard_context():
    """Gather all dashboard statistics and metrics."""
    now = timezone.now()
    today = now.date()
    last_7_days = today - timedelta(days=7)
    last_30_days = today - timedelta(days=30)
    
    # === DATABASE RECORD COUNTS ===
    patient_count = Patient.objects.count()
    order_count = ExamOrder.objects.count()
    report_count = Report.objects.count()
    claim_count = Claim.objects.count()
    facility_count = Facility.objects.count()
    device_count = Device.objects.count()
    modality_count = Modality.objects.count()
    payer_count = InsurancePayer.objects.count()
    
    # === TODAY'S ACTIVITY ===
    orders_today = ExamOrder.objects.filter(
        created_at__date=today
    ).count()
    
    reports_today = Report.objects.filter(
        created_at__date=today
    ).count()
    
    # === RECENT TRENDS (Last 7 days) ===
    orders_last_7 = ExamOrder.objects.filter(
        created_at__date__gte=last_7_days
    ).count()
    
    reports_last_7 = Report.objects.filter(
        created_at__date__gte=last_7_days
    ).count()
    
    # === ORDER STATUS BREAKDOWN ===
    order_status_counts = ExamOrder.objects.values('status').annotate(
        count=Count('id')
    )
    
    # === MODALITY DISTRIBUTION ===
    modality_distribution = ExamOrder.objects.values(
        'modality__code'
    ).annotate(
        count=Count('id'),
        modality_name=Count('modality__name')
    ).order_by('-count')[:10]
    
    # === FACILITY STATISTICS ===
    facility_stats = Facility.objects.annotate(
        order_count=Count('exam_orders', distinct=True),
        device_count=Count('devices', distinct=True)
    ).order_by('-order_count')[:5]
    
    # === BILLING METRICS ===
    total_billed = ServiceLine.objects.filter(
        total_charge__isnull=False
    ).aggregate(total=Sum('total_charge'))['total'] or 0
    
    total_paid = Payment.objects.aggregate(
        total=Sum('amount')
    )['total'] or 0
    
    pending_claims = Claim.objects.filter(
        status='pending'
    ).count()
    
    denied_claims = Claim.objects.filter(
        status='denied'
    ).count()
    
    # === CLAIM STATUS BREAKDOWN ===
    claim_status_counts = Claim.objects.values('status').annotate(
        count=Count('id')
    )
    
    # === REVENUE BY PAYER ===
    revenue_by_payer = ServiceLine.objects.filter(
        claim__payer__isnull=False,
        total_charge__isnull=False
    ).values(
        'claim__payer__name'
    ).annotate(
        total_revenue=Sum('total_charge')
    ).order_by('-total_revenue')[:10]
    
    # === ORDERS TREND (Last 30 days) ===
    orders_trend = ExamOrder.objects.filter(
        created_at__date__gte=last_30_days
    ).annotate(
        date=TruncDay('created_at')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')
    
    # === TOP PROCEDURES ===
    top_procedures = ExamOrder.objects.values(
        'procedure_code',
        'procedure_name_en'
    ).annotate(
        order_count=Count('id')
    ).order_by('-order_count')[:10]
    
    context = {
        # Record counts
        'patient_count': patient_count,
        'order_count': order_count,
        'report_count': report_count,
        'claim_count': claim_count,
        'facility_count': facility_count,
        'device_count': device_count,
        'modality_count': modality_count,
        'payer_count': payer_count,
        
        # Today's activity
        'orders_today': orders_today,
        'reports_today': reports_today,
        
        # Recent trends
        'orders_last_7': orders_last_7,
        'reports_last_7': reports_last_7,
        
        # Order status
        'order_status_counts': list(order_status_counts),
        
        # Modality distribution
        'modality_distribution': list(modality_distribution),
        
        # Facility stats
        'facility_stats': list(facility_stats),
        
        # Billing metrics
        'total_billed': total_billed,
        'total_paid': total_paid,
        'pending_claims': pending_claims,
        'denied_claims': denied_claims,
        
        # Claim status
        'claim_status_counts': list(claim_status_counts),
        
        # Revenue by payer
        'revenue_by_payer': list(revenue_by_payer),
        
        # Orders trend
        'orders_trend': list(orders_trend),
        
        # Top procedures
        'top_procedures': list(top_procedures),
    }
    
    return context


def dashboard_stats_api(request):
    """API endpoint for dashboard statistics."""
    context = get_dashboard_context()
    return JsonResponse(context)


def orders_by_modality_chart(request):
    """Chart data: Orders grouped by modality."""
    now = timezone.now()
    last_30_days = now.date() - timedelta(days=30)
    
    modality_data = ExamOrder.objects.filter(
        created_at__date__gte=last_30_days,
        modality__isnull=False
    ).values(
        'modality__code',
        'modality__name'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    chart_data = {
        'labels': [f"{item['modality__code']} - {item['modality__name']}" 
                   for item in modality_data],
        'datasets': [{
            'label': 'Orders by Modality (Last 30 Days)',
            'data': [item['count'] for item in modality_data],
            'backgroundColor': [
                '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b',
                '#858796', '#5a5c69', '#6610f2', '#fd7e14', '#20c997'
            ][:len(modality_data)]
        }]
    }
    
    return JsonResponse(chart_data)


def orders_trend_chart(request):
    """Chart data: Orders trend over time."""
    now = timezone.now()
    last_30_days = now.date() - timedelta(days=30)
    
    trend_data = ExamOrder.objects.filter(
        created_at__date__gte=last_30_days
    ).annotate(
        date=TruncDay('created_at')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')
    
    chart_data = {
        'labels': [item['date'].strftime('%Y-%m-%d') for item in trend_data],
        'datasets': [{
            'label': 'Daily Orders',
            'data': [item['count'] for item in trend_data],
            'borderColor': '#4e73df',
            'backgroundColor': 'rgba(78, 115, 223, 0.1)',
            'tension': 0.3,
            'fill': True
        }]
    }
    
    return JsonResponse(chart_data)


def revenue_by_payer_chart(request):
    """Chart data: Revenue by insurance payer."""
    payer_data = ServiceLine.objects.filter(
        claim__payer__isnull=False,
        total_charge__isnull=False
    ).values(
        'claim__payer__name'
    ).annotate(
        total_revenue=Sum('total_charge')
    ).order_by('-total_revenue')[:10]
    
    chart_data = {
        'labels': [item['claim__payer__name'] for item in payer_data],
        'datasets': [{
            'label': 'Revenue by Payer',
            'data': [float(item['total_revenue']) if item['total_revenue'] else 0 
                     for item in payer_data],
            'backgroundColor': [
                '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b',
                '#858796', '#5a5c69', '#6610f2', '#fd7e14', '#20c997'
            ][:len(payer_data)]
        }]
    }
    
    return JsonResponse(chart_data)


def claims_status_chart(request):
    """Chart data: Claims status distribution."""
    status_data = Claim.objects.values('status').annotate(
        count=Count('id')
    )
    
    chart_data = {
        'labels': [item['status'] or 'Unknown' for item in status_data],
        'datasets': [{
            'label': 'Claims by Status',
            'data': [item['count'] for item in status_data],
            'backgroundColor': [
                '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b'
            ][:len(status_data)]
        }]
    }
    
    return JsonResponse(chart_data)
