"""PACS study browsing, retrieval and diagnostics views (PACS plan Phase 4).

Phase 4 acceptance criteria addressed here:
- Task 4.1: facility-scoped, paginated, validated study list + detail page
  with order/report linkage, archive state and actionable errors; staff
  diagnostics view showing system state only (no DICOM payloads, no secrets).
- Task 4.2: every DICOM retrieval is mediated by this trusted backend —
  authorization happens against the mirror row *before* any archive access,
  responses are streamed through Django from the Orthanc adapter, and the
  browser never receives archive credentials or filesystem paths.

Security posture (plan §3 trust boundary):
- All queries start from ``reconciliation.scoped_studies`` so URL-ID
  manipulation cannot reach another facility's studies (404 instead of 403
  to avoid leaking existence).
- Reconciliation POST actions re-check ``can_reconcile`` server-side.
- PHI responses set ``no-store`` cache headers.
- Access to study content is audited (``pacs.study_view`` /
  ``pacs.dicom_retrieve``) via the existing audit infrastructure.
"""

import logging
import re
import urllib.request

from django.conf import settings
from django.contrib import messages as django_messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from clinic.permissions import accessible_facility_ids, record_audit
from core.models import Device, Facility
from orders.models import ExamOrder
from pacs import reconciliation
from pacs.metrics import collect_metrics
from pacs.models import PACSStudy, StudyStatus, SyncEvent
from pacs.orthanc_client import OrthancClient, OrthancError

logger = logging.getLogger(__name__)

# Hard cap on page size even if a caller asks for more (bounded queries).
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25

# Accepted search inputs are deliberately narrow; anything longer is a
# client mistake, not a query we should run.
ACCESSION_MAX_LEN = 50
UID_RE = re.compile(r"^[0-9.]{1,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

STATUS_LABELS = dict(StudyStatus.choices)


def _no_phi_cache(response):
    """PHI must not be cached by browsers/proxies (Task 4.2 caching rules)."""
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def _study_or_404(request, pk):
    """Fetch a study strictly inside the user's facility scope.

    Cross-facility or unowned studies raise 404 (existence not leaked).
    """
    qs = reconciliation.scoped_studies(request.user)
    return get_object_or_404(qs, pk=pk)


def _parse_filters(request):
    """Validate and normalize GET filters. Returns (filters, errors, raw)."""
    raw = request.GET
    errors = []
    f = {
        "q": (raw.get("q") or "").strip()[:120],
        "accession": (raw.get("accession") or "").strip()[:ACCESSION_MAX_LEN],
        "uid": (raw.get("uid") or "").strip(),
        "modality": (raw.get("modality") or "").strip()[:16].upper(),
        "status": (raw.get("status") or "").strip(),
        "order_status": (raw.get("order_status") or "").strip(),
        "facility": (raw.get("facility") or "").strip(),
        "date_from": (raw.get("date_from") or "").strip(),
        "date_to": (raw.get("date_to") or "").strip(),
        "page": (raw.get("page") or "1").strip(),
        "page_size": (raw.get("page_size") or str(DEFAULT_PAGE_SIZE)).strip(),
    }

    if f["uid"] and not UID_RE.match(f["uid"]):
        errors.append(_("Study Instance UID contains invalid characters."))
        f["uid"] = ""

    valid_statuses = {c[0] for c in StudyStatus.choices}
    if f["status"] and f["status"] not in valid_statuses:
        errors.append(_("Unknown archive status filter."))
        f["status"] = ""

    valid_order_statuses = {c[0] for c in ExamOrder.Status.choices}
    if f["order_status"] and f["order_status"] not in valid_order_statuses:
        errors.append(_("Unknown order status filter."))
        f["order_status"] = ""

    for key in ("date_from", "date_to"):
        if f[key] and not DATE_RE.match(f[key]):
            errors.append(_("Invalid date format (use YYYY-MM-DD)."))
            f[key] = ""

    try:
        f["page_size"] = min(max(int(f["page_size"]), 1), MAX_PAGE_SIZE)
    except ValueError:
        f["page_size"] = DEFAULT_PAGE_SIZE
    try:
        f["page"] = max(int(f["page"]), 1)
    except ValueError:
        f["page"] = 1

    # Facility filter only honored within the user's own scope.
    if f["facility"]:
        ids = accessible_facility_ids(request.user)
        if ids is not None and f["facility"] not in {str(i) for i in ids}:
            errors.append(_("Facility outside your permitted scope."))
            f["facility"] = ""

    return f, errors, raw


@login_required
def study_list(request):
    """Facility-scoped, searchable, paginated study list (Task 4.1)."""
    f, errors, _raw = _parse_filters(request)

    qs = reconciliation.scoped_studies(request.user).select_related(
        "facility", "matched_order", "matched_order__patient", "sender_device"
    )

    if f["q"]:
        qs = qs.filter(
            Q(accession_number__icontains=f["q"])
            | Q(patient_id_as_received__icontains=f["q"])
            | Q(patient_name_as_received__icontains=f["q"])
            | Q(study_instance_uid__icontains=f["q"])
        )
    if f["accession"]:
        qs = qs.filter(accession_number__iexact=f["accession"])
    if f["uid"]:
        qs = qs.filter(study_instance_uid=f["uid"])
    if f["modality"]:
        qs = qs.filter(modality__iexact=f["modality"])
    if f["status"]:
        qs = qs.filter(status=f["status"])
    if f["facility"]:
        qs = qs.filter(facility_id=f["facility"])
    if f["order_status"]:
        qs = qs.filter(matched_order__status=f["order_status"])
    if f["date_from"]:
        qs = qs.filter(study_datetime__date__gte=f["date_from"])
    if f["date_to"]:
        qs = qs.filter(study_datetime__date__lte=f["date_to"])

    # Bounded ordering: study_datetime falls back to created_at rows.
    qs = qs.order_by("-study_datetime", "-created_at")

    paginator = Paginator(qs, f["page_size"], orphans=5)
    try:
        page_obj = paginator.get_page(f["page"])
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        "page_obj": page_obj,
        "paginator": paginator,
        "filters": f,
        "filter_errors": errors,
        "status_choices": StudyStatus.choices,
        "order_status_choices": ExamOrder.Status.choices,
        "modalities": sorted(
            {m for m in PACSStudy.objects.exclude(modality="").values_list(
                "modality", flat=True
            ).distinct() if m}
        ),
        "total_studies": paginator.count,
        "can_reconcile": reconciliation.can_reconcile(request.user),
    }
    return _no_phi_cache(render(request, "pacs/study_list.html", context))


@login_required
def study_detail(request, pk):
    """Study detail: linkage, counts, archive state, actionable errors."""
    study = _study_or_404(request, pk)
    study = (
        PACSStudy.objects.select_related(
            "facility", "sender_device", "matched_order",
            "matched_order__patient", "matched_order__modality",
        )
        .get(pk=study.pk)
    )

    # Audit read access to a study record (identifiers only, no payload).
    record_audit(
        request,
        "pacs.study_view",
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        old=None,
        new={"accession": study.accession_number, "status": study.status},
    )

    reports = []
    order = study.matched_order
    if order is not None:
        from reports.models import Report  # local import: app dependency

        reports = (
            Report.objects.filter(order=order)
            .order_by("-created_at")[:10]
        )

    series_preview = []
    archive_error = ""
    if study.orthanc_study_id:
        try:
            client = OrthancClient()
            data = client.get_study(study.orthanc_study_id, expand=True) or {}
            for s in data.get("Series", [])[:50]:
                tags = s.get("MainTags", {}) if isinstance(s, dict) else {}
                series_preview.append(
                    {
                        "id": s.get("ID", "") if isinstance(s, dict) else str(s),
                        "description": tags.get("0003,0010", ""),
                        "modality": tags.get("0008,0060", ""),
                        "count": s.get("CountInstances", "") if isinstance(s, dict) else "",
                    }
                )
        except OrthancError as exc:
            archive_error = type(exc).__name__

    can_reconcile = reconciliation.can_reconcile(request.user)
    facilities = []
    if can_reconcile:
        ids = accessible_facility_ids(request.user)
        fac_qs = Facility.objects.all()
        if ids is not None:
            fac_qs = fac_qs.filter(id__in=ids)
        facilities = list(fac_qs.order_by("name"))

    context = {
        "study": study,
        "status_label": STATUS_LABELS.get(study.status, study.status),
        "order": order,
        "reports": reports,
        "series_preview": series_preview,
        "archive_error": archive_error,
        "can_reconcile": can_reconcile,
        "facilities": facilities,
        "link_preview": None,
        "now": timezone.now(),
    }
    return _no_phi_cache(render(request, "pacs/study_detail.html", context))


@login_required
@require_POST
def study_action(request, pk):
    """Reconciliation actions from the detail page (server-side gated)."""
    study = _study_or_404(request, pk)
    if not reconciliation.can_reconcile(request.user):
        raise PermissionDenied(_("You are not allowed to reconcile studies."))

    action = request.POST.get("action", "")
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        django_messages.error(request, _("A written reason is required."))
        return redirect("pacs:study_detail", pk=study.pk)

    try:
        if action == "link":
            order_pk = (request.POST.get("order_pk") or "").strip()
            # Accept a UUID directly, or resolve an accession number typed by
            # the user. Ambiguous/missing accessions are refused, never
            # guessed (matching policy stays deterministic).
            if not _UUID_RE.match(order_pk):
                acc = order_pk  # treat non-UUID input as an accession search
                ids0 = accessible_facility_ids(request.user)
                oqs0 = ExamOrder.objects.filter(
                    accession_number__iexact=acc, is_deleted=False
                )
                if ids0 is not None:
                    oqs0 = oqs0.filter(facility_id__in=ids0)
                if oqs0.count() != 1:
                    raise ValueError(
                        _("Enter a unique accession number or exact order id.")
                    )
                order_pk = str(oqs0.first().pk)

            # Scoped order lookup — guessed ids outside the user's facilities
            # are not found, and never linked.
            ids = accessible_facility_ids(request.user)
            oqs = ExamOrder.objects.filter(pk=order_pk, is_deleted=False)
            if ids is not None:
                oqs = oqs.filter(facility_id__in=ids)
            order = oqs.first()
            if order is None:
                raise ValueError(_("Order not found in your permitted scope."))
            diffs = reconciliation.preview_link(study, order)
            if diffs and request.POST.get("confirm") != "yes":
                # Show conflicts first; do not silently link (Task 3.3 rule).
                context = {
                    "study": study,
                    "order": order,
                    "diffs": diffs,
                    "reason": reason,
                }
                return _no_phi_cache(
                    render(request, "pacs/confirm_link.html", context)
                )
            reconciliation.manual_link(request.user, study.pk, order.pk, reason)
            django_messages.success(request, _("Study linked to the order."))
        elif action == "unlink":
            reconciliation.manual_unlink(request.user, study.pk, reason)
            django_messages.success(request, _("Link removed; study kept in archive."))
        elif action == "incorrect":
            reconciliation.mark_incorrectly_received(request.user, study.pk, reason)
            django_messages.success(request, _("Study marked as incorrectly received."))
        elif action == "move":
            target_fac = request.POST.get("target_facility") or ""
            reconciliation.move_facility(request.user, study.pk, target_fac, reason)
            django_messages.success(request, _("Study moved between facilities."))
        elif action == "escalate":
            reconciliation.escalate(request.user, study.pk, reason)
            django_messages.success(request, _("Study escalated to a supervisor."))
        elif action == "rematch":
            reconciliation.rematch(request.user, study.pk)
            django_messages.success(request, _("Automatic matching re-run."))
        else:
            django_messages.error(request, _("Unknown action."))
    except (ValueError, PermissionDenied) as exc:
        django_messages.error(request, str(exc))
    return redirect("pacs:study_detail", pk=study.pk)


@login_required
def retrieve_dicom(request, pk):
    """Authorized DICOM retrieval proxy (Task 4.2).

    The browser gets original application/dicom bytes streamed from the
    archive through this view; it never sees archive URLs or credentials.
    Authorization is checked against the scoped mirror row FIRST.
    """
    study = _study_or_404(request, pk)

    if not study.orthanc_study_id:
        return _no_phi_cache(
            HttpResponse(_("Study is not present in the archive yet."), status=409)
        )

    record_audit(
        request,
        "pacs.dicom_retrieve",
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        old=None,
        new={"kind": "zip-archive"},
    )

    client = OrthancClient()
    try:
        body = client.get_study_archive_zip(study.orthanc_study_id)
    except OrthancError as exc:
        logger.warning(
            "retrieve failed for study %s: %s", study.pk, type(exc).__name__
        )
        return _no_phi_cache(
            HttpResponse(_("The archive is currently unavailable."), status=502)
        )

    filename = f"study-{study.accession_number or study.study_instance_uid}.zip"
    response = HttpResponse(body, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return _no_phi_cache(response)


@login_required
def instance_file(request, pk, instance_id):
    """Single-instance retrieval; instance id must belong to this study."""
    if not re.match(r"^[A-Za-z0-9_-]{1,64}$", instance_id):
        return HttpResponse(status=400)
    study = _study_or_404(request, pk)

    client = OrthancClient()
    try:
        info = client._request(f"/instances/{instance_id}")
    except OrthancError:
        return HttpResponse(status=404)
    parent_study = (info or {}).get("ParentStudy", "")
    if parent_study != study.orthanc_study_id:
        # Guessed instance id that belongs to a different study → deny.
        raise PermissionDenied(_("Instance does not belong to this study."))

    record_audit(
        request,
        "pacs.dicom_retrieve",
        entity_type="PACSStudy",
        entity_id=str(study.pk),
        old=None,
        new={"kind": "instance", "instance": instance_id},
    )

    try:
        file_bytes = client.get_instance_file(instance_id)
    except OrthancError:
        return HttpResponse(_("The archive is currently unavailable."), status=502)

    response = HttpResponse(file_bytes, content_type="application/dicom")
    response["Content-Disposition"] = f'inline; filename="instance-{instance_id}.dcm"'
    return _no_phi_cache(response)


@login_required
def diagnostics(request):
    """Staff-facing system diagnostics (Task 4.1): state only.

    No DICOM payloads, no credentials, no configuration secrets — counts,
    queue depths, lag, health categories and recent error categories.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        raise PermissionDenied(_("Staff access required."))

    metrics = collect_metrics()

    recent_failures = list(
        SyncEvent.objects.filter(outcome=SyncEvent.Outcome.FAILED)
        .order_by("-change")[:20]
        .values("change", "error_category", "attempts", "processed_at")
    )

    devices = []
    ids = accessible_facility_ids(request.user)
    dev_qs = Device.objects.select_related("facility", "modality")
    if ids is not None:
        dev_qs = dev_qs.filter(facility_id__in=ids)
    for d in dev_qs.order_by("facility__name", "name")[:100]:
        devices.append(
            {
                "name": d.name,
                "ae_title": getattr(d, "dicom_ae_title", ""),
                "facility": d.facility.name if d.facility else None,
            }
        )

    context = {
        "metrics": metrics,
        "recent_failures": recent_failures,
        "devices": devices,
        "generated_at": metrics.get("generated_at"),
    }
    return _no_phi_cache(render(request, "pacs/diagnostics.html", context))
