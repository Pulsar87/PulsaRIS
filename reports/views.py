from django.contrib import messages
from django.shortcuts import redirect, render, get_object_or_404
from django.utils.translation import gettext as _
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Q
from orders.models import ExamOrder
from reports.models import Report
from patients.views import get_tenant
import uuid
from datetime import datetime
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from pydicom.sequence import Sequence


def create_report(request, order_id):
    """Create a new report for an exam order."""
    tenant = get_tenant(request)
    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:worklist")

    order = get_object_or_404(ExamOrder, id=order_id, tenant=tenant)

    if request.method == "POST":
        report_content = request.POST.get("report_content", "").strip()
        status = request.POST.get("status", Report.Status.DRAFT)

        # Parse content to separate findings and impression if needed
        # For now, store full content in findings_en
        findings_en = report_content

        # Create new report
        report = Report.objects.create(
            tenant=tenant,
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
        report_content = request.POST.get("report_content", "").strip()
        status = request.POST.get("status", report.status)

        # Update report
        report.findings_en = report_content
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

def report_list(request):
    """Display list of all reports with advanced filtering."""
    query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    radiologist_filter = request.GET.get("radiologist", "")
    modality_filter = request.GET.get("modality", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    critical_filter = request.GET.get("critical", "")
    tenant = get_tenant(request)

    reports = Report.objects.none()
    modalities = []
    radiologists = []

    if tenant:
        from tenants.models import Modality
        from users.models import User

        modalities = Modality.objects.filter(tenant=tenant, is_active=True)

        # Get radiologists who have created reports
        radiologists = User.objects.filter(
            is_staff=True,
            report__tenant=tenant
        ).distinct().order_by("username")

        reports = Report.objects.filter(tenant=tenant).select_related(
            "order__patient", "order__modality", "radiologist"
        )

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
        "modalities": modalities,
        "radiologists": radiologists,
    }
    return render(request, "reports/report_list.html", context)



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
    report_content = request.POST.get("report_content", "")

    # Get or create draft report
    report, created = Report.objects.get_or_create(
        order=order,
        radiologist=request.user,
        status=Report.Status.DRAFT,
        defaults={
            "tenant": tenant,
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


def export_report_dicom(request, report_id):
    """Export a report as a DICOM SR (Structured Report) file."""
    tenant = get_tenant(request)
    if not tenant:
        messages.error(request, _("Tenant not found. Please select a tenant."))
        return redirect("orders:worklist")

    report = get_object_or_404(Report, id=report_id, tenant=tenant)

    try:
        # Create DICOM dataset for Structured Report
        ds = Dataset()

        # Set SOP Class UID for Basic Text SR
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.88.11"  # Basic Text SR IOD
        ds.SOPInstanceUID = generate_uid()
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()

        # Patient Information
        patient = report.order.patient
        ds.PatientName = f"{patient.last_name_en}^{patient.first_name_en}"
        ds.PatientID = patient.mrn or ""
        ds.PatientSex = patient.gender or ""
        if patient.dob:
            ds.PatientBirthDate = patient.dob.strftime("%Y%m%d")

        # Study Information
        ds.StudyID = report.order.accession_number or str(uuid.uuid4())[:8]
        ds.AccessionNumber = report.order.accession_number or ""
        ds.StudyDescription = report.order.procedure_name_en or "Radiology Report"
        if report.order.scheduled_datetime:
            ds.StudyDate = report.order.scheduled_datetime.strftime("%Y%m%d")
            ds.StudyTime = report.order.scheduled_datetime.strftime("%H%M%S")
        else:
            ds.StudyDate = report.created_at.strftime("%Y%m%d")
            ds.StudyTime = report.created_at.strftime("%H%M%S")

        # Series Information
        ds.Modality = "SR"  # Structured Report
        ds.SeriesNumber = "1"
        ds.SeriesDescription = "Radiology Report"

        # Equipment Information
        ds.Manufacturer = "Pulsar RIS"
        ds.InstitutionName = tenant.name if hasattr(tenant, 'name') else ""

        # Content - encode the report findings and impression
        content_items = []

        # Add findings
        if report.findings_en:
            findings_text = report.findings_en
            content_items.append(f"FINDINGS:\n{findings_text}")

        # Add impression
        if report.impression_en:
            impression_text = report.impression_en
            content_items.append(f"\nIMPRESSION:\n{impression_text}")

        # Combine content
        report_content = "\n\n".join(content_items) if content_items else "No report content available."

        # Create a simple text file content for the SR
        import tempfile
        import os

        # Create temporary file with report content
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        temp_file.write("=" * 60 + "\n")
        temp_file.write("RADIOLOGY REPORT\n")
        temp_file.write("=" * 60 + "\n\n")
        temp_file.write(f"Accession Number: {ds.AccessionNumber}\n")
        temp_file.write(f"Patient Name: {ds.PatientName}\n")
        temp_file.write(f"Patient ID: {ds.PatientID}\n")
        temp_file.write(f"Study Date: {ds.StudyDate}\n")
        temp_file.write(f"Modality: {ds.Modality}\n")
        temp_file.write(f"Procedure: {report.order.procedure_name_en}\n")
        temp_file.write(f"Radiologist: {report.radiologist.username}\n")
        temp_file.write(f"Status: {report.status}\n")
        if report.finalized_at:
            temp_file.write(f"Finalized: {report.finalized_at.strftime('%Y-%m-%d %H:%M:%S')}\n")
        temp_file.write("\n" + "=" * 60 + "\n")
        temp_file.write(report_content)
        temp_file.write("\n\n" + "=" * 60 + "\n")
        temp_file.write(f"Report ID: {report.id}\n")
        temp_file.write(f"Created: {report.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n")
        temp_file.write(f"Updated: {report.updated_at.strftime('%Y-%m-%d %H:%M:%S')}\n")
        temp_file.close()

        # Read the file content
        with open(temp_file.name, 'rb') as f:
            file_content = f.read()

        # Clean up temp file
        os.unlink(temp_file.name)

        # Create FileDataset
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
        file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.ImplementationClassUID = "1.2.3.4.5.6.7.8.9.10"

        # Create the FileDataset instance
        ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)

        # Copy all attributes
        for attr in [
            'SOPClassUID', 'SOPInstanceUID', 'StudyInstanceUID', 'SeriesInstanceUID',
            'PatientName', 'PatientID', 'PatientSex', 'PatientBirthDate',
            'StudyID', 'AccessionNumber', 'StudyDescription', 'StudyDate', 'StudyTime',
            'Modality', 'SeriesNumber', 'SeriesDescription',
            'Manufacturer', 'InstitutionName'
        ]:
            if hasattr(ds, attr):
                setattr(ds, attr, getattr(ds, attr))

        # Add the report content as encapsulated document
        ds.ContentSequence = Sequence([Dataset()])
        content_ds = ds.ContentSequence[0]
        content_ds.RelationshipType = "CONTAINS"
        content_ds.ValueType = "TEXT"
        content_ds.TextValue = report_content

        # Save to BytesIO for HTTP response
        from io import BytesIO
        buffer = BytesIO()
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.save_as(buffer, write_like_original=False)
        buffer.seek(0)

        # Create filename
        filename = f"report_{report.id}_{report.order.accession_number}.dcm"

        response = HttpResponse(buffer.getvalue(), content_type="application/dicom")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        messages.error(request, _("Error exporting report: %(error)s") % {"error": str(e)})
        return redirect("reports:view_report", report_id=report_id)
