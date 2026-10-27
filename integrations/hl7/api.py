"""DRF API for the HL7 lab/vitals receiver service.

Read endpoints expose stored messages and their normalized vitals; a POST
ingest endpoint accepts raw HL7 (JSON body or text/plain) so HTTP-capable
devices and internal systems can feed the same pipeline as the MLLP listener.
"""

from __future__ import annotations

from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.hl7.models import HL7VitalMessage
from integrations.hl7.services import persist_payload


class HL7VitalMessageSerializer(serializers.ModelSerializer):
    patient_id = serializers.CharField(read_only=True)
    patient_name = serializers.CharField(read_only=True)

    class Meta:
        model = HL7VitalMessage
        fields = [
            "id", "received_at", "remote_host", "remote_port",
            "sender_identity", "sending_application", "sending_facility",
            "message_control_id", "message_type", "trigger_event",
            "payload_sha256", "status", "error", "duplicate_of",
            "patient_id", "patient_name",
            "spo2", "spo2_unit", "pulse_rate", "pulse_rate_unit",
            "respiratory_rate", "respiratory_rate_unit",
            "systolic_bp", "systolic_bp_unit",
            "diastolic_bp", "diastolic_bp_unit",
            "mean_bp", "mean_bp_unit",
            "nibp_pulse_rate", "nibp_pulse_rate_unit",
            "heart_rate", "heart_rate_unit",
            "body_temperature", "body_temperature_unit",
            "etco2", "etco2_unit", "fio2", "fio2_unit",
            "weight", "weight_unit", "height", "height_unit",
            "blood_type", "device_software_version", "respiratory_rate_source",
        ]


def _apply_filters(queryset, params):
    status_value = params.get("status")
    if status_value:
        queryset = queryset.filter(status=status_value)
    message_type = params.get("message_type")
    if message_type:
        queryset = queryset.filter(message_type=message_type.upper())
    control_id = params.get("control_id")
    if control_id:
        queryset = queryset.filter(message_control_id=control_id)
    sender = params.get("sender")
    if sender:
        queryset = queryset.filter(sender_identity__icontains=sender)
    patient = params.get("patient")
    if patient:
        # parsed_json is a JSON column; filter on the extracted patient id.
        queryset = queryset.filter(parsed_json__patient__patient_id=patient)
    since = params.get("since")
    if since:
        day = parse_date(since)
        if day:
            queryset = queryset.filter(received_at__date__gte=day)
    until = params.get("until")
    if until:
        day = parse_date(until)
        if day:
            queryset = queryset.filter(received_at__date__lte=day)
    return queryset


class HL7MessageListView(APIView):
    """Paginated list of received HL7 messages with dedicated vital columns."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = _apply_filters(HL7VitalMessage.objects.all(), request.query_params)
        try:
            page_size = min(max(int(request.query_params.get("page_size", 50)), 1), 200)
        except (TypeError, ValueError):
            page_size = 50
        total = queryset.count()
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
        except (TypeError, ValueError):
            page = 1
        start = (page - 1) * page_size
        rows = queryset[start : start + page_size]
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": HL7VitalMessageSerializer(rows, many=True).data,
            }
        )


class HL7MessageDetailView(APIView):
    """One message including the full parsed document and normalized vitals."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        message = HL7VitalMessage.objects.filter(pk=pk).first()
        if not message:
            return Response({"detail": "Not found."}, status=404)
        include_raw = request.query_params.get("raw", "0") in {"1", "true", "yes"}
        return Response(message.to_api_dict(include_raw=include_raw))


class HL7IngestView(APIView):
    """HTTP ingestion of raw HL7 v2 messages into the same storage pipeline.

    Accepts ``text/plain`` / ``application/hl7-v2`` bodies (optionally inside
    MLLP framing) or JSON ``{"hl7": "<raw message>"}``. Returns the stored
    record disposition plus a rendered ACK string when requested.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        content_type = (request.content_type or "").split(";")[0].strip().lower()
        if content_type == "application/json" and isinstance(request.data, dict):
            raw_text = str(request.data.get("hl7") or request.data.get("message") or "")
        else:
            raw_text = request.body.decode("utf-8", errors="replace")
        # Tolerate devices that wrap HTTP payloads in MLLP framing characters.
        raw_text = raw_text.strip("\x0b\x1c\r\n \t")
        if not raw_text.strip():
            return Response({"detail": "Empty HL7 payload."}, status=400)

        want_ack = str(request.query_params.get("ack", "1")).lower() not in {"0", "false", "no"}
        outcome = persist_payload(raw_text.encode("utf-8"), remote_host=request.META.get("REMOTE_ADDR", ""))
        payload = {
            "id": outcome["id"],
            "status": outcome["status"],
            "error": outcome["error"],
            "control_id": outcome["control_id"],
            "message_type": outcome["message_type"],
        }
        if want_ack:
            from integrations.hl7.protocol import make_ack

            code = "AA" if outcome["status"] in {"accepted", "duplicate"} else "AE"
            detail = "Message stored" if outcome["status"] == "accepted" else (outcome["error"] or "Message rejected")
            payload["ack"] = make_ack(outcome["parsed"], code, detail)
        return Response(payload, status=201 if outcome["status"] == "accepted" else 200)
