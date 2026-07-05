"""
Billing Reporting Service
Provides data aggregation and analytics for financial reports
"""
from datetime import datetime, timedelta
from decimal import Decimal
from django.db.models import Sum, Count, Avg, Q, F
from django.utils import timezone
from .models import (
    ServiceLine, Claim, PaymentPosting, Payment, 
    PatientStatement, ClaimAppeal, DenialReason
)


class ReportingService:
    """Service class for generating billing reports and analytics"""
    
    def __init__(self, tenant):
        self.tenant = tenant
    
    def get_charge_capture_report(self, start_date, end_date):
        """Daily Charge Capture Report - Service lines created in date range"""
        service_lines = ServiceLine.objects.filter(
            tenant=self.tenant,
            created_at__date__range=(start_date, end_date)
        )
        
        total_charges = service_lines.aggregate(total=Sum('charge_amount'))['total'] or Decimal('0.00')
        total_units = service_lines.aggregate(total=Sum('units'))['total'] or 0
        
        # Group by status
        status_breakdown = service_lines.values('status').annotate(
            count=Count('id'),
            total_charges=Sum('charge_amount')
        )
        
        # Group by provider
        provider_breakdown = service_lines.values('rendering_provider').annotate(
            count=Count('id'),
            total_charges=Sum('charge_amount')
        )
        
        # Daily trend
        daily_trend = service_lines.extra(
            select={'date': 'DATE(created_at)'}
        ).values('date').annotate(
            count=Count('id'),
            total_charges=Sum('charge_amount')
        ).order_by('date')
        
        return {
            'summary': {
                'total_service_lines': service_lines.count(),
                'total_charges': total_charges,
                'total_units': total_units,
                'average_charge': total_charges / service_lines.count() if service_lines.count() > 0 else Decimal('0.00')
            },
            'status_breakdown': list(status_breakdown),
            'provider_breakdown': list(provider_breakdown),
            'daily_trend': list(daily_trend)
        }
    
    def get_claim_submission_report(self, start_date, end_date):
        """Claim Submission Report - Claims created/submitted in date range"""
        claims = Claim.objects.filter(
            tenant=self.tenant,
            created_at__date__range=(start_date, end_date)
        )
        
        total_billed = claims.aggregate(total=Sum('total_billed_amount'))['total'] or Decimal('0.00')
        
        # Group by status
        status_breakdown = claims.values('claim_status').annotate(
            count=Count('id'),
            total_billed=Sum('total_billed_amount')
        )
        
        # Group by payer
        payer_breakdown = claims.values('payer__name').annotate(
            count=Count('id'),
            total_billed=Sum('total_billed_amount')
        )
        
        # Submission method breakdown
        submission_breakdown = claims.values('submission_method').annotate(
            count=Count('id')
        )
        
        return {
            'summary': {
                'total_claims': claims.count(),
                'total_billed': total_billed,
                'average_claim_value': total_billed / claims.count() if claims.count() > 0 else Decimal('0.00')
            },
            'status_breakdown': list(status_breakdown),
            'payer_breakdown': list(payer_breakdown),
            'submission_breakdown': list(submission_breakdown)
        }
    
    def get_payment_posting_report(self, start_date, end_date):
        """Payment Posting Report - Payments posted in date range"""
        postings = PaymentPosting.objects.filter(
            tenant=self.tenant,
            posting_date__date__range=(start_date, end_date)
        )
        
        total_payments = postings.aggregate(total=Sum('payment_amount'))['total'] or Decimal('0.00')
        total_adjustments = postings.aggregate(total=Sum('adjustment_amount'))['total'] or Decimal('0.00')
        
        # Group by payer
        payer_breakdown = postings.values('payer__name').annotate(
            count=Count('id'),
            total_payment=Sum('payment_amount'),
            total_adjustment=Sum('adjustment_amount')
        )
        
        # Group by posting type
        type_breakdown = postings.values('posting_type').annotate(
            count=Count('id'),
            total_payment=Sum('payment_amount')
        )
        
        return {
            'summary': {
                'total_postings': postings.count(),
                'total_payments': total_payments,
                'total_adjustments': total_adjustments,
                'net_revenue': total_payments + total_adjustments  # Adjustments are typically negative
            },
            'payer_breakdown': list(payer_breakdown),
            'type_breakdown': list(type_breakdown)
        }
    
    def get_ar_aging_report(self, as_of_date):
        """Accounts Receivable Aging Report"""
        # Get all unpaid/underpaid claims
        aging_buckets = {
            'current': {'min': 0, 'max': 30},
            'days_31_60': {'min': 31, 'max': 60},
            'days_61_90': {'min': 61, 'max': 90},
            'days_91_120': {'min': 91, 'max': 120},
            'over_120': {'min': 121, 'max': 9999}
        }
        
        results = {}
        total_ar = Decimal('0.00')
        
        for bucket_name, bucket_range in aging_buckets.items():
            min_days = bucket_range['min']
            max_days = bucket_range['max']
            
            # Calculate date range for this bucket
            max_date = as_of_date - timedelta(days=min_days)
            min_date = as_of_date - timedelta(days=max_days)
            
            # Get claims in this aging bucket
            claims = Claim.objects.filter(
                tenant=self.tenant,
                claim_status__in=['submitted', 'pending', 'partially_paid'],
                created_at__date__lte=max_date,
                created_at__date__gt=min_date if min_date else None
            )
            
            bucket_total = claims.aggregate(
                total=Sum(F('total_billed_amount') - F('total_paid_amount'))
            )['total'] or Decimal('0.00')
            
            results[bucket_name] = {
                'count': claims.count(),
                'amount': bucket_total
            }
            
            total_ar += bucket_total
        
        # Group by payer
        payer_aging = Claim.objects.filter(
            tenant=self.tenant,
            claim_status__in=['submitted', 'pending', 'partially_paid']
        ).values('payer__name').annotate(
            ar_balance=Sum(F('total_billed_amount') - F('total_paid_amount'))
        )
        
        return {
            'summary': {
                'total_ar': total_ar,
                'as_of_date': as_of_date
            },
            'aging_buckets': results,
            'payer_breakdown': list(payer_aging)
        }
    
    def get_denial_management_report(self, start_date, end_date):
        """Denial Management Report"""
        denied_claims = Claim.objects.filter(
            tenant=self.tenant,
            claim_status='denied',
            updated_at__date__range=(start_date, end_date)
        )
        
        total_denied_amount = denied_claims.aggregate(total=Sum('total_billed_amount'))['total'] or Decimal('0.00')
        
        # Group by denial reason
        reason_breakdown = denied_claims.values('denial_reason__code').annotate(
            count=Count('id'),
            total_amount=Sum('total_billed_amount')
        )
        
        # Appeals status
        appeals_with_claims = ClaimAppeal.objects.filter(
            tenant=self.tenant,
            claim__in=denied_claims
        ).values('appeal_status').annotate(count=Count('id'))
        
        # Denial rate calculation
        total_claims = Claim.objects.filter(
            tenant=self.tenant,
            created_at__date__range=(start_date, end_date)
        ).count()
        
        denial_rate = (denied_claims.count() / total_claims * 100) if total_claims > 0 else 0
        
        return {
            'summary': {
                'total_denied_claims': denied_claims.count(),
                'total_denied_amount': total_denied_amount,
                'denial_rate': round(denial_rate, 2),
                'total_claims': total_claims
            },
            'reason_breakdown': list(reason_breakdown),
            'appeals_status': list(appeals_with_claims)
        }
    
    def get_revenue_analysis_report(self, start_date, end_date):
        """Revenue Analysis Report"""
        # Total revenue from payments
        payments = Payment.objects.filter(
            tenant=self.tenant,
            payment_date__date__range=(start_date, end_date)
        )
        
        total_revenue = payments.aggregate(total=Sum('payment_amount'))['total'] or Decimal('0.00')
        
        # Revenue by payment method
        method_breakdown = payments.values('payment_method').annotate(
            total=Sum('payment_amount'),
            count=Count('id')
        )
        
        # Revenue by payer (from payment postings)
        postings = PaymentPosting.objects.filter(
            tenant=self.tenant,
            posting_date__date__range=(start_date, end_date)
        )
        
        payer_revenue = postings.values('payer__name').annotate(
            total_payment=Sum('payment_amount'),
            total_adjustment=Sum('adjustment_amount')
        )
        
        # Monthly trend
        monthly_trend = payments.extra(
            select={'month': "DATE_FORMAT(payment_date, '%Y-%m')"}
        ).values('month').annotate(
            total=Sum('payment_amount'),
            count=Count('id')
        ).order_by('month')
        
        return {
            'summary': {
                'total_revenue': total_revenue,
                'total_payments': payments.count(),
                'average_payment': total_revenue / payments.count() if payments.count() > 0 else Decimal('0.00')
            },
            'method_breakdown': list(method_breakdown),
            'payer_revenue': list(payer_revenue),
            'monthly_trend': list(monthly_trend)
        }
    
    def get_collection_metrics_report(self, start_date, end_date):
        """Collection Metrics Dashboard"""
        # Collection Rate
        total_billed = Claim.objects.filter(
            tenant=self.tenant,
            created_at__date__lte=end_date
        ).aggregate(total=Sum('total_billed_amount'))['total'] or Decimal('0.00')
        
        total_collected = PaymentPosting.objects.filter(
            tenant=self.tenant,
            posting_date__date__range=(start_date, end_date)
        ).aggregate(total=Sum('payment_amount'))['total'] or Decimal('0.00')
        
        collection_rate = (total_collected / total_billed * 100) if total_billed > 0 else 0
        
        # Days in A/R
        ar_balance = Claim.objects.filter(
            tenant=self.tenant,
            claim_status__in=['submitted', 'pending', 'partially_paid']
        ).aggregate(
            total=Sum(F('total_billed_amount') - F('total_paid_amount'))
        )['total'] or Decimal('0.00')
        
        avg_daily_charges = Claim.objects.filter(
            tenant=self.tenant,
            created_at__date__range=(start_date, end_date)
        ).aggregate(total=Sum('total_billed_amount'))['total'] or Decimal('0.00')
        
        days_in_ar = (ar_balance / (avg_daily_charges / 30)) if avg_daily_charges > 0 else 0
        
        # First Pass Resolution Rate
        first_pass_claims = Claim.objects.filter(
            tenant=self.tenant,
            created_at__date__range=(start_date, end_date),
            claim_status__in=['paid', 'submitted', 'pending']
        ).count()
        
        total_claims = Claim.objects.filter(
            tenant=self.tenant,
            created_at__date__range=(start_date, end_date)
        ).count()
        
        first_pass_rate = (first_pass_claims / total_claims * 100) if total_claims > 0 else 0
        
        # Cost to Collect (simplified)
        total_payments_count = Payment.objects.filter(
            tenant=self.tenant,
            payment_date__date__range=(start_date, end_date)
        ).count()
        
        return {
            'summary': {
                'collection_rate': round(collection_rate, 2),
                'days_in_ar': round(days_in_ar, 1),
                'first_pass_resolution_rate': round(first_pass_rate, 2),
                'total_ar_balance': ar_balance,
                'total_collected': total_collected,
                'total_billed': total_billed
            },
            'activity_metrics': {
                'total_claims': total_claims,
                'total_payments': total_payments_count
            }
        }
