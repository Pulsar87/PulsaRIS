from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render, get_object_or_404
from django.utils.translation import gettext as _
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Q
from clinic.permissions import accessible_facility_ids
from orders.models import ExamOrder
from reports.models import Report
import logging

logger = logging.getLogger(__name__)


def _reports_for_user(user, qs=None):
    from clinic.permissions import accessible_facility_ids

    if qs is None:
        qs = Report.objects.select_related("order__patient", "order__modality", "radiologist")
    ids = accessible_facility_ids(user)
    if ids is None:
        return qs
    if not ids:
        return qs.none()
    return qs.filter(order__facility_id__in=ids)


def _require_report_access(request):
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    ids = accessible_facility_ids(request.user)
    if ids is not None and not ids:
        raise PermissionDenied("No facility access.")


@login_required
def create_report(request, order_id):
    """Create a new report for an exam order."""
    _require_report_access(request)
    ids = accessible_facility_ids(request.user)
    if ids is None:
        order = get_object_or_404(ExamOrder, id=order_id)
    else:
        order = get_object_or_404(ExamOrder.objects.filter(facility_id__in=ids), id=order_id)

    if request.method == "POST":
        report_content = request.POST.get("report_content", "").strip()
        status = request.POST.get("status", Report.Status.DRAFT)

        # Parse content to separate findings and impression if needed
        # For now, store full content in findings_en
        findings_en = report_content

        # Create new report
        report = Report.objects.create(
            order=order,
            radiologist=request.user,
            findings_en=findings_en,
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
        "status_choices": Report.Status.choices,
    }
    return render(request, "reports/report_form.html", context)


@login_required
def edit_report(request, report_id):
    """Edit an existing report or view finalized reports with export/print options."""
    _require_report_access(request)
    report = get_object_or_404(_reports_for_user(request.user, Report.objects.select_related("order", "radiologist")), id=report_id)

    # Check permission - only the author or staff can access
    if report.radiologist != request.user and not request.user.is_staff:
        messages.error(request, _("You don't have permission to access this report."))
        return redirect("reports:view_report", report_id=report_id)

    # AMENDED reports can only be edited by staff, but all authorized users can view/print
    if report.status == Report.Status.AMENDED and not request.user.is_staff and request.method == "POST":
        messages.error(request, _("Amended reports can only be edited by supervising physicians."))
        return redirect("reports:view_report", report_id=report_id)

    if request.method == "POST":
        if report.status == Report.Status.FINAL:
            messages.error(request, _("Finalized reports cannot be edited. Please use the Amend function to make changes."))
            return redirect("reports:edit_report", report_id=report.id)

        report_content = request.POST.get("report_content", "").strip()
        allowed_statuses = {Report.Status.DRAFT, Report.Status.PRELIMINARY}
        if request.user.is_staff:
            requested_status = request.POST.get("status", report.status)
            if requested_status not in allowed_statuses and requested_status != Report.Status.FINAL:
                requested_status = report.status
            status = requested_status
        else:
            status = report.status
            if request.POST.get("status") == Report.Status.FINAL:
                messages.warning(request, _("Only supervising physicians can finalize reports."))
                status = Report.Status.PRELIMINARY

        report.findings_en = report_content
        report.status = status

        if status == Report.Status.FINAL and not report.finalized_at:
            report.finalized_at = timezone.now()

        report.save()

        if status == Report.Status.FINAL:
            report.order.status = ExamOrder.Status.REPORTED
            report.order.save(update_fields=["status"])

        messages.success(request, _("Report updated successfully!"))
        return redirect("reports:view_report", report_id=report.id)

    context = {
        "order": report.order,
        "report": report,
        "status_choices": Report.Status.choices,
    }
    return render(request, "reports/report_form.html", context)


@login_required
def verify_report(request, report_id):
    """Verify/finalize a report (only for doctors/staff)."""
    _require_report_access(request)
    report = get_object_or_404(_reports_for_user(request.user, Report.objects.select_related("order")), id=report_id)

    if not request.user.is_staff:
        messages.error(request, _("Only supervising physicians can verify reports."))
        return redirect("reports:view_report", report_id=report_id)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "verify":
            old_status = report.status
            report.status = Report.Status.FINAL
            report.finalized_at = timezone.now()
            report.signed_at = timezone.now()
            report.save()

            report.order.status = ExamOrder.Status.REPORTED
            report.order.save(update_fields=["status"])

            try:
                from audit.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action='VERIFY',
                    entity_type='Report',
                    entity_id=report.id,
                    old_values={'status': old_status},
                    new_values={'status': Report.Status.FINAL, 'finalized_at': str(report.finalized_at)},
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                )
            except Exception:
                pass

            messages.success(request, _("Report verified and finalized successfully!"))

        elif action == "amend":
            if report.status == Report.Status.FINAL:
                report.status = Report.Status.AMENDED
                report.version += 1
                report.finalized_at = timezone.now()
                report.save()

                try:
                    from audit.models import AuditLog
                    AuditLog.objects.create(
                        user=request.user,
                        action='AMEND',
                        entity_type='Report',
                        entity_id=report.id,
                        old_values={'status': Report.Status.FINAL, 'version': report.version - 1},
                        new_values={'status': Report.Status.AMENDED, 'version': report.version},
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                    )
                except Exception:
                    pass

                messages.success(request, _("Report marked as amended. Please update the content."))

        return redirect("reports:view_report", report_id=report.id)

    context = {
        "report": report,
        "order": report.order,
    }
    return render(request, "reports/report_verify.html", context)


@login_required
def view_report(request, report_id):
    """View a single report."""
    _require_report_access(request)
    report = get_object_or_404(_reports_for_user(request.user, Report.objects.select_related("order")), id=report_id)

    context = {
        "report": report,
        "order": report.order,
    }
    return render(request, "reports/report_detail.html", context)


@login_required
def study_reports(request, order_id):
    """View all reports for a study/order."""
    _require_report_access(request)
    ids = accessible_facility_ids(request.user)
    if ids is None:
        order = get_object_or_404(ExamOrder, id=order_id)
    else:
        order = get_object_or_404(ExamOrder.objects.filter(facility_id__in=ids), id=order_id)
    reports = order.reports.all().order_by("-created_at")

    context = {
        "order": order,
        "reports": reports,
    }
    return render(request, "reports/study_reports.html", context)


@login_required
def delete_report(request, report_id):
    """Delete a report (soft delete with audit logging)."""
    _require_report_access(request)
    from audit.models import AuditLog

    report = get_object_or_404(_reports_for_user(request.user, Report.objects.select_related("order")), id=report_id)
    order_id = report.order.id

    # Check permission - only staff can delete
    if not request.user.is_staff:
        messages.error(request, _("You don't have permission to delete this report."))
        return redirect("reports:view_report", report_id=report_id)

    if request.method == "POST":
        try:
            # Store old values for audit
            old_values = {
                'status': report.status,
                'findings_en': report.findings_en[:200] if report.findings_en else '',
                'impression_en': report.impression_en[:200] if report.impression_en else '',
            }
            
            # Soft delete instead of hard delete
            report.soft_delete()
            
            # Create audit log entry
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action='DELETE',
                entity_type='Report',
                entity_id=report.id,
                old_values=old_values,
                new_values={'is_deleted': True, 'deleted_at': str(report.deleted_at)},
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        
            messages.success(request, _("Report deleted successfully!"))
            return redirect("reports:study_reports", order_id=order_id)
        except Exception as e:
            messages.error(request, _("Error deleting report: %(error)s") % {"error": str(e)})
            return redirect("reports:view_report", report_id=report_id)

    context = {
        "report": report,
        "order": report.order,
    }
    return render(request, "reports/report_confirm_delete.html", context)

@login_required
def report_list(request):
    """Display list of all reports with advanced filtering."""
    _require_report_access(request)
    query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    radiologist_filter = request.GET.get("radiologist", "")
    modality_filter = request.GET.get("modality", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    critical_filter = request.GET.get("critical", "")

    reports = _reports_for_user(request.user, Report.objects.select_related(
        "order__patient", "order__modality", "radiologist"
    ))

    # Search filter
    if query:
        reports = reports.filter(
            Q(id__icontains=query)
            | Q(order__accession_number__icontains=query)
            | Q(order__patient__mrn__icontains=query)
            | Q(order__patient__first_name_en__icontains=query)
            | Q(order__patient__last_name_en__icontains=query)
            | Q(findings_en__icontains=query)
            | Q(impression_en__icontains=query)
        )

    # Status filter
    if status_filter:
        reports = reports.filter(status=status_filter)

    # Radiologist filter
    if radiologist_filter:
        reports = reports.filter(radiologist_id=radiologist_filter)

    # Modality filter (via order)
    if modality_filter:
        reports = reports.filter(order__modality__code=modality_filter)

    # Date range filters
    if date_from:
        reports = reports.filter(created_at__date__gte=date_from)

    if date_to:
        reports = reports.filter(created_at__date__lte=date_to)

    # Critical finding filter
    if critical_filter == "true":
        reports = reports.filter(critical_finding=True)
    elif critical_filter == "false":
        reports = reports.filter(critical_finding=False)

    from users.models import User
    # Get radiologists who have created reports
    radiologists = User.objects.filter(
        is_staff=True,
    ).distinct().order_by("username")

    context = {
        "reports": reports,
        "query": query,
        "status_filter": status_filter,
        "radiologist_filter": radiologist_filter,
        "modality_filter": modality_filter,
        "date_from": date_from,
        "date_to": date_to,
        "critical_filter": critical_filter,
        "status_choices": Report.Status.choices,
        "radiologists": radiologists,
    }
    return render(request, "reports/report_list.html", context)



@login_required
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


@login_required
@require_http_methods(["POST"])
def save_report_draft(request):
    """Save a report as draft via AJAX (auto-save functionality)."""
    _require_report_access(request)
    order_id = request.POST.get("order_id")
    if not order_id:
        return JsonResponse({"error": "Order ID required"}, status=400)

    ids = accessible_facility_ids(request.user)
    if ids is None:
        order = get_object_or_404(ExamOrder, id=order_id)
    else:
        order = get_object_or_404(ExamOrder.objects.filter(facility_id__in=ids), id=order_id)
    report_content = request.POST.get("report_content", "")

    # Get or create draft report
    report, created = Report.objects.get_or_create(
        order=order,
        radiologist=request.user,
        status=Report.Status.DRAFT,
        defaults={
            "findings_en": report_content,
        }
    )

    if not created:
        report.findings_en = report_content
        report.save()

    return JsonResponse({
        "success": True,
        "report_id": str(report.id),
        "message": "Draft saved successfully"
    })


@login_required
def export_report_dicom(request, report_id):
    """Export a finalized report as a DICOM SR file (PACS plan Task 5.1).

    The dataset is built by ``pacs.sr_export``: the SR is linked to the
    order's real imaging StudyInstanceUID (never an invented one), gets
    fresh unique Series/SOP instance UIDs, and is also stored into the
    archive when reachable. Reports without a valid study linkage are
    blocked with a clear message -- the documented standalone-export
    policy for this deployment (no silent relationship invention).
    Signed report text is never mutated here.
    """
    _require_report_access(request)
    report = get_object_or_404(
        _reports_for_user(request.user, Report.objects.select_related("order")), id=report_id
    )

    # Only allow export if report is finalized (FINAL or AMENDED status)
    if report.status not in [Report.Status.FINAL, Report.Status.AMENDED]:
        messages.error(request, _("Only finalized reports can be exported."))
        return redirect("reports:study_reports", order_id=report.order.id)

    from pacs.orthanc_client import OrthancError
    from pacs.sr_export import SRLinkageError, store_sr_for_report

    try:
        data, orthanc_id = store_sr_for_report(report)
    except SRLinkageError as exc:
        record_audit(
            request,
            "export_denied",
            entity_type="Report",
            entity_id=str(report.id),
            new={"reason": exc.message[:500]},
        )
        messages.error(request, exc.message)
        return redirect("reports:study_reports", order_id=report.order.id)
    except Exception as e:  # pragma: no cover - defensive, keeps old UX
        logger.exception("SR export failed for report %s", report.id)
        messages.error(request, _("Error exporting report: %(error)s") % {"error": str(e)[:300]})
        return redirect("reports:view_report", report_id=report_id)

    record_audit(
        request,
        "export",
        entity_type="Report",
        entity_id=str(report.id),
        new={
            "format": "dicom_sr",
            "study_uid": report.order.dicom_study_instance_uid or "",
            "archive_stored": bool(orthanc_id),
            "orthanc_instance": orthanc_id,
        },
    )

    filename = f"report_{report.id}_{report.order.accession_number}.dcm"
    response = HttpResponse(data, content_type="application/dicom")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
