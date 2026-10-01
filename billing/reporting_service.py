"""Billing reports built from the billing models."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Sum, Value
from django.db.models.functions import TruncDate, TruncMonth

from .models import Claim, ClaimAppeal, ClaimLine, Payment, PaymentPosting, ServiceLine


class ReportingService:
    """Generate billing reports for the configured single-database deployment."""

    def get_charge_capture_report(self, start_date, end_date):
        service_lines = ServiceLine.objects.filter(
            created_at__date__range=(start_date, end_date)
        )
        totals = service_lines.aggregate(
            total_charges=Sum("total_charge"),
            total_units=Sum("quantity"),
        )
        count = service_lines.count()
        status_breakdown = service_lines.values("billing_status").annotate(
            count=Count("id"),
            total_charges=Sum("total_charge"),
        )
        provider_breakdown = service_lines.values("rendering_provider").annotate(
            count=Count("id"),
            total_charges=Sum("total_charge"),
        )
        daily_trend = service_lines.annotate(date=TruncDate("created_at")).values(
            "date"
        ).annotate(
            count=Count("id"),
            total_charges=Sum("total_charge"),
        ).order_by("date")

        return {
            "summary": {
                "total_service_lines": count,
                "total_charges": totals["total_charges"] or Decimal("0.00"),
                "total_units": totals["total_units"] or 0,
                "average_charge": (
                    (totals["total_charges"] or Decimal("0.00")) / count
                    if count
                    else Decimal("0.00")
                ),
            },
            "status_breakdown": list(status_breakdown),
            "provider_breakdown": list(provider_breakdown),
            "daily_trend": list(daily_trend),
        }

    def get_claim_submission_report(self, start_date, end_date):
        claims = Claim.objects.filter(created_at__date__range=(start_date, end_date))
        total_billed = claims.aggregate(total=Sum("total_charges"))["total"] or Decimal("0.00")
        count = claims.count()

        return {
            "summary": {
                "total_claims": count,
                "total_billed": total_billed,
                "average_claim_value": total_billed / count if count else Decimal("0.00"),
            },
            "status_breakdown": list(
                claims.values("status").annotate(
                    count=Count("id"),
                    total_billed=Sum("total_charges"),
                )
            ),
            "payer_breakdown": list(
                claims.values("payer__name").annotate(
                    count=Count("id"),
                    total_billed=Sum("total_charges"),
                )
            ),
            "submission_breakdown": list(
                claims.values("claim_type").annotate(count=Count("id"))
            ),
        }

    def get_payment_posting_report(self, start_date, end_date):
        postings = PaymentPosting.objects.filter(posting_date__range=(start_date, end_date))
        totals = postings.aggregate(total=Sum("payment_amount"))
        payment_total = totals["total"] or Decimal("0.00")
        count = postings.count()
        payer_breakdown = list(
            postings.values("payer__name").annotate(
                count=Count("id"),
                total_payment=Sum("payment_amount"),
                total_adjustment=Value(
                    Decimal("0.00"),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                ),
            )
        )
        type_breakdown = list(
            postings.values("payment_method").annotate(
                count=Count("id"),
                total_payment=Sum("payment_amount"),
            )
        )
        return {
            "summary": {
                "total_postings": count,
                "total_payments": payment_total,
                "total_adjustments": Decimal("0.00"),
                "net_revenue": payment_total,
            },
            "payer_breakdown": payer_breakdown,
            "type_breakdown": type_breakdown,
        }

    def get_ar_aging_report(self, as_of_date):
        aging_ranges = {
            "current": (0, 30),
            "days_31_60": (31, 60),
            "days_61_90": (61, 90),
            "days_91_120": (91, 120),
            "over_120": (121, None),
        }
        open_claims = Claim.objects.filter(
            status__in=("SUBMITTED", "ACCEPTED", "PARTIAL")
        )
        results = {}
        total_ar = Decimal("0.00")

        for bucket_name, (minimum_days, maximum_days) in aging_ranges.items():
            latest_service_date = as_of_date - timedelta(days=minimum_days)
            claims = open_claims.filter(date_of_service_from__lte=latest_service_date)
            if maximum_days is not None:
                earliest_service_date = as_of_date - timedelta(days=maximum_days)
                claims = claims.filter(date_of_service_from__gt=earliest_service_date)
            bucket_total = claims.aggregate(
                total=Sum(F("total_charges") - F("paid_amount"))
            )["total"] or Decimal("0.00")
            results[bucket_name] = {"count": claims.count(), "amount": bucket_total}
            total_ar += bucket_total

        payer_breakdown = open_claims.values("payer__name").annotate(
            ar_balance=Sum(F("total_charges") - F("paid_amount"))
        )
        return {
            "summary": {"total_ar": total_ar, "as_of_date": as_of_date},
            "aging_buckets": results,
            "payer_breakdown": list(payer_breakdown),
        }

    def get_denial_management_report(self, start_date, end_date):
        denied_claims = Claim.objects.filter(
            status="DENIED",
            updated_at__date__range=(start_date, end_date),
        )
        total_denied_amount = denied_claims.aggregate(
            total=Sum("total_charges")
        )["total"] or Decimal("0.00")
        total_claims = Claim.objects.filter(
            created_at__date__range=(start_date, end_date)
        ).count()
        denied_count = denied_claims.count()
        reason_breakdown = ClaimLine.objects.filter(
            claim__in=denied_claims
        ).values("denial_code").annotate(
            count=Count("id"),
            total_amount=Sum("charge_amount"),
        )
        appeals_status = ClaimAppeal.objects.filter(
            claim__in=denied_claims
        ).values("status").annotate(count=Count("id"))

        return {
            "summary": {
                "total_denied_claims": denied_count,
                "total_denied_amount": total_denied_amount,
                "denial_rate": round(denied_count / total_claims * 100, 2)
                if total_claims
                else 0,
                "total_claims": total_claims,
            },
            "reason_breakdown": list(reason_breakdown),
            "appeals_status": list(appeals_status),
        }

    def get_revenue_analysis_report(self, start_date, end_date):
        payments = Payment.objects.filter(
            payment_date__date__range=(start_date, end_date)
        )
        total_revenue = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        payment_count = payments.count()
        postings = PaymentPosting.objects.filter(
            posting_date__range=(start_date, end_date)
        )

        return {
            "summary": {
                "total_revenue": total_revenue,
                "total_payments": payment_count,
                "average_payment": (
                    total_revenue / payment_count if payment_count else Decimal("0.00")
                ),
            },
            "method_breakdown": list(
                payments.values("payment_method").annotate(
                    total=Sum("amount"),
                    count=Count("id"),
                )
            ),
            "payer_revenue": list(
                postings.values("payer__name").annotate(
                    total_payment=Sum("payment_amount"),
                    total_adjustment=Value(
                        Decimal("0.00"),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    ),
                )
            ),
            "monthly_trend": list(
                payments.annotate(month=TruncMonth("payment_date")).values(
                    "month"
                ).annotate(
                    total=Sum("amount"),
                    count=Count("id"),
                ).order_by("month")
            ),
        }

    def get_collection_metrics_report(self, start_date, end_date):
        claims_in_period = Claim.objects.filter(
            created_at__date__range=(start_date, end_date)
        )
        total_billed = claims_in_period.aggregate(
            total=Sum("total_charges")
        )["total"] or Decimal("0.00")
        total_collected = PaymentPosting.objects.filter(
            posting_date__range=(start_date, end_date)
        ).aggregate(total=Sum("payment_amount"))["total"] or Decimal("0.00")

        open_claims = Claim.objects.filter(
            status__in=("SUBMITTED", "ACCEPTED", "PARTIAL")
        )
        ar_balance = open_claims.aggregate(
            total=Sum(F("total_charges") - F("paid_amount"))
        )["total"] or Decimal("0.00")
        days_in_ar = (
            ar_balance / (total_billed / 30)
            if total_billed
            else Decimal("0.0")
        )
        total_claims = claims_in_period.count()
        first_pass_claims = claims_in_period.exclude(
            status__in=("DENIED", "REJECTED")
        ).count()

        return {
            "summary": {
                "collection_rate": round(total_collected / total_billed * 100, 2)
                if total_billed
                else 0,
                "days_in_ar": round(days_in_ar, 1),
                "first_pass_resolution_rate": round(
                    first_pass_claims / total_claims * 100, 2
                )
                if total_claims
                else 0,
                "total_ar_balance": ar_balance,
                "total_collected": total_collected,
                "total_billed": total_billed,
            },
            "activity_metrics": {
                "total_claims": total_claims,
                "total_payments": Payment.objects.filter(
                    payment_date__date__range=(start_date, end_date)
                ).count(),
            },
        }
