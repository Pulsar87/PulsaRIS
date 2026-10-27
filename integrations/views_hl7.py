"""Staff web UI for the HL7 lab/vitals receiver (list + detail)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date

from integrations.hl7.models import HL7VitalMessage, MessageStatus

PAGE_SIZE = 25


def _filters(params):
    applied = {
        "q": (params.get("q") or "").strip()[:120],
        "status": (params.get("status") or "").strip(),
        "sender": (params.get("sender") or "").strip()[:120],
        "since": params.get("since") or "",
        "until": params.get("until") or "",
    }
    queryset = HL7VitalMessage.objects.all()
    if applied["q"]:
        from django.db.models import Q

        term = applied["q"]
        queryset = queryset.filter(
            Q(message_control_id__icontains=term)
            | Q(payload_sha256__startswith=term)
            | Q(raw_hl7__icontains=term)
        )
    if applied["status"] in set(MessageStatus.values):
        queryset = queryset.filter(status=applied["status"])
    else:
        applied["status"] = ""
    if applied["sender"]:
        queryset = queryset.filter(sender_identity__icontains=applied["sender"])
    if applied["since"] and parse_date(applied["since"]):
        queryset = queryset.filter(received_at__date__gte=parse_date(applied["since"]))
    else:
        applied["since"] = ""
    if applied["until"] and parse_date(applied["until"]):
        queryset = queryset.filter(received_at__date__lte=parse_date(applied["until"]))
    else:
        applied["until"] = ""
    return queryset, applied


@login_required
def message_list(request):
    queryset, applied = _filters(request.GET)
    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "integrations/hl7_message_list.html",
        {
            "page_obj": page_obj,
            "filters": applied,
            "status_choices": MessageStatus.choices,
            "total_count": paginator.count,
        },
    )


@login_required
def message_detail(request, pk: int):
    message = get_object_or_404(HL7VitalMessage, pk=pk)
    return render(
        request,
        "integrations/hl7_message_detail.html",
        {"message": message, "parsed_json": message.parsed_json or {}, "vitals_json": message.vitals_json or {}},
    )
