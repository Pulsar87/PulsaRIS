from django.contrib import messages
from django.shortcuts import redirect, render, get_object_or_404
from django.utils.translation import gettext as _
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from orders.models import ExamOrder
from reports.models import Report
from patients.views import get_tenant


def create_report(request, order_id):
    """Create a new report for an exam order."""
    tenant = get_tenant(request)
    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:worklist")
    
    order = get_object_or_404(ExamOrder, id=order_id, tenant=tenant)
    
    if request.method == "POST":
        findings_en = request.POST.get("findings_en", "").strip()
        findings_ar = request.POST.get("findings_ar", "").strip()
        impression_en = request.POST.get("impression_en", "").strip()
        impression_ar = request.POST.get("impression_ar", "").strip()
        critical_finding = request.POST.get("critical_finding") == "on"
        status = request.POST.get("status", Report.Status.DRAFT)
        
        # Create new report
        report = Report.objects.create(
            tenant=tenant,
            order=order,
            radiologist=request.user,
            findings_en=findings_en,
            findings_ar=findings_ar,
            impression_en=impression_en,
            impression_ar=impression_ar,
            critical_finding=critical_finding,
            status=status,
        )
        
        # Update order status if report is finalized
        if status == Report.Status.FINAL:
            order.status = ExamOrder.Status.REPORTED
            order.save(update_fields=["status"])
        
        messages.success(request, _("Report created successfully!"))
        return redirect("reports:view_report", report_id=report.id)
    
    context = {
        "order": order,
        "report": None,
    }
    return render(request, "reports/report_form.html", context)


def edit_report(request, report_id):
    """Edit an existing report."""
    tenant = get_tenant(request)
    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:worklist")
    
    report = get_object_or_404(Report, id=report_id, tenant=tenant)
    
    # Check permission - only the author or staff can edit
    if report.radiologist != request.user and not request.user.is_staff:
        messages.error(request, _("You don't have permission to edit this report."))
        return redirect("reports:view_report", report_id=report_id)
    
    if request.method == "POST":
        findings_en = request.POST.get("findings_en", "").strip()
        findings_ar = request.POST.get("findings_ar", "").strip()
        impression_en = request.POST.get("impression_en", "").strip()
        impression_ar = request.POST.get("impression_ar", "").strip()
        critical_finding = request.POST.get("critical_finding") == "on"
        status = request.POST.get("status", report.status)
        
        # Update report
        report.findings_en = findings_en
        report.findings_ar = findings_ar
        report.impression_en = impression_en
        report.impression_ar = impression_ar
        report.critical_finding = critical_finding
        report.status = status
        
        if status == Report.Status.FINAL and not report.finalized_at:
            report.finalized_at = timezone.now()
        
        report.save()
        
        # Update order status if report is finalized
        if status == Report.Status.FINAL:
            report.order.status = ExamOrder.Status.REPORTED
            report.order.save(update_fields=["status"])
        
        messages.success(request, _("Report updated successfully!"))
        return redirect("reports:view_report", report_id=report.id)
    
    context = {
        "order": report.order,
        "report": report,
    }
    return render(request, "reports/report_form.html", context)


def view_report(request, report_id):
    """View a single report."""
    tenant = get_tenant(request)
    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:worklist")
    
    report = get_object_or_404(Report, id=report_id, tenant=tenant)
    
    context = {
        "report": report,
        "order": report.order,
    }
    return render(request, "reports/report_detail.html", context)


def study_reports(request, order_id):
    """View all reports for a study/order."""
    tenant = get_tenant(request)
    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:worklist")
    
    order = get_object_or_404(ExamOrder, id=order_id, tenant=tenant)
    reports = order.reports.all().order_by("-created_at")
    
    context = {
        "order": order,
        "reports": reports,
    }
    return render(request, "reports/study_reports.html", context)


def delete_report(request, report_id):
    """Delete a report."""
    tenant = get_tenant(request)
    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:worklist")
    
    report = get_object_or_404(Report, id=report_id, tenant=tenant)
    order_id = report.order.id
    
    # Check permission - only staff can delete
    if not request.user.is_staff:
        messages.error(request, _("You don't have permission to delete this report."))
        return redirect("reports:view_report", report_id=report_id)
    
    if request.method == "POST":
        report.delete()
        messages.success(request, _("Report deleted successfully!"))
        return redirect("reports:study_reports", order_id=order_id)
    
    context = {
        "report": report,
        "order": report.order,
    }
    return render(request, "reports/report_confirm_delete.html", context)


@require_http_methods(["GET"])
def get_report_templates(request):
    """Get available report templates via AJAX."""
    # TODO: Implement template retrieval from database or config
    templates = [
        {"id": 1, "name": "Normal CT Head", "content": "No acute intracranial abnormality."},
        {"id": 2, "name": "Normal MRI Knee", "content": "No internal derangement identified."},
        {"id": 3, "name": "Normal Chest X-ray", "content": "No acute cardiopulmonary process."},
    ]
    return JsonResponse({"templates": templates})


@require_http_methods(["POST"])
def save_report_draft(request):
    """Save a report as draft via AJAX (auto-save functionality)."""
    tenant = get_tenant(request)
    if not tenant:
        return JsonResponse({"error": "Tenant not found"}, status=400)
    
    order_id = request.POST.get("order_id")
    if not order_id:
        return JsonResponse({"error": "Order ID required"}, status=400)
    
    order = get_object_or_404(ExamOrder, id=order_id, tenant=tenant)
    findings_en = request.POST.get("findings_en", "")
    findings_ar = request.POST.get("findings_ar", "")
    impression_en = request.POST.get("impression_en", "")
    impression_ar = request.POST.get("impression_ar", "")
    
    # Get or create draft report
    report, created = Report.objects.get_or_create(
        order=order,
        radiologist=request.user,
        status=Report.Status.DRAFT,
        defaults={
            "tenant": tenant,
            "findings_en": findings_en,
            "findings_ar": findings_ar,
            "impression_en": impression_en,
            "impression_ar": impression_ar,
        }
    )
    
    if not created:
        report.findings_en = findings_en
        report.findings_ar = findings_ar
        report.impression_en = impression_en
        report.impression_ar = impression_ar
        report.save()
    
    return JsonResponse({
        "success": True,
        "report_id": str(report.id),
        "message": "Draft saved successfully"
    })
