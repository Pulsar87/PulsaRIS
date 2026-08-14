"""
DICOM Modality Worklist SCP Server Management Command

Starts a DICOM server that listens for C-FIND requests and returns
worklist items from the database.

Usage:
    python manage.py run_dicom_server [--host HOST] [--port PORT] [--ae-title AE_TITLE]

Examples:
    python manage.py run_dicom_server
    python manage.py run_dicom_server --port 11112
    python manage.py run_dicom_server --host 0.0.0.0 --port 11112 --ae-title RIS_SCP
"""

import sys

from django.core.management.base import BaseCommand
from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.sop_class import Verification, ModalityWorklistInformationFind

from orders.models import ExamOrder
from tenants.models import Device, Modality


class Command(BaseCommand):
    help = "Run DICOM Modality Worklist SCP server"

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default="0.0.0.0",
            help="Host to bind the server (default: 0.0.0.0)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=11112,
            help="Port to listen on (default: 11112)",
        )
        parser.add_argument(
            "--ae-title",
            type=str,
            default="RIS_SCP",
            help="AE Title for the server (default: RIS_SCP)",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]
        ae_title = options["ae_title"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting DICOM Modality Worklist SCP server...\n"
                f"AE Title: {ae_title}\n"
                f"Listening on: {host}:{port}\n"
                f"Press Ctrl+C to stop\n"
            )
        )

        # Initialize Application Entity
        ae = AE(ae_title)
        handlers = [(evt.EVT_C_FIND, self.handle_find)]

        # Add supported contexts
        ae.add_supported_context(Verification)
        ae.add_supported_context(ModalityWorklistInformationFind)

        # Start server
        try:
            ae.start_server((host, port), evt_handlers=handlers, block=True)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nServer stopped by user."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Server error: {e}"))
            sys.exit(1)

    def handle_find(self, event):
        """
        Handle C-FIND-RQ messages.
        """
        # Access the identifier dataset for C-FIND requests
        try:
            request = event.identifier
        except AttributeError:
            # Fallback for different pynetdicom versions
            request = event.dataset

        # Extract filters
        modality_filter = getattr(request, "Modality", None)
        station_ae_filter = getattr(request, "ScheduledStationAETitle", None)
        patient_name_filter = getattr(request, "PatientName", None)
        patient_id_filter = getattr(request, "PatientID", None)

        self.stdout.write(
            f"Received C-FIND from {event.association.requestor.ae_title}: "
            f"Modality={modality_filter or '*'}, Station={station_ae_filter or '*'}"
        )

        # Get matching worklist items
        matches = self.get_worklist_items(request)

        if not matches:
            self.stdout.write("No matching worklist items found.")
            yield (0x0000, None)  # Success with no matches
            return

        self.stdout.write(f"Found {len(matches)} matching worklist items.")

        # Return each match
        for item in matches:
            yield (0xFF00, item)  # Pending (more matches coming)

        yield (0x0000, None)  # Success (no more matches)

    def get_worklist_items(self, request_dataset):
        """
        Query the database for worklist items matching the request filters.
        Returns a list of Datasets representing worklist items.
        """
        # Extract filters from request
        modality_filter = getattr(request_dataset, "Modality", None)
        station_ae_filter = getattr(request_dataset, "ScheduledStationAETitle", None)
        patient_name_filter = getattr(request_dataset, "PatientName", None)
        patient_id_filter = getattr(request_dataset, "PatientID", None)

        # Build queryset - no tenant filtering needed in single-tenant setup
        queryset = ExamOrder.objects.select_related(
            "patient", "modality", "room_station"
        ).filter(status__in=[ExamOrder.Status.REGISTERED, ExamOrder.Status.SCHEDULED])

        if modality_filter and modality_filter != "*":
            # Map DICOM modality codes to database modality codes
            queryset = queryset.filter(modality__code__iexact=modality_filter)

        if station_ae_filter and station_ae_filter != "*":
            queryset = queryset.filter(room_station__dicom_ae_title=station_ae_filter)

        if patient_name_filter and patient_name_filter != "*":
            if "*" in patient_name_filter:
                pattern = patient_name_filter.replace("*", "")
                queryset = queryset.filter(
                    patient__first_name_en__icontains=pattern
                ) | queryset.filter(patient__last_name_en__icontains=pattern)
            else:
                queryset = queryset.filter(
                    patient__first_name_en__icontains=patient_name_filter
                ) | queryset.filter(
                    patient__last_name_en__icontains=patient_name_filter
                )

        if patient_id_filter and patient_id_filter != "*":
            if "*" in patient_id_filter:
                pattern = patient_id_filter.replace("*", "")
                queryset = queryset.filter(patient__mrn__icontains=pattern)
            else:
                queryset = queryset.filter(patient__mrn=patient_id_filter)

        # Convert to DICOM datasets
        all_items = []
        for order in queryset[:100]:  # Limit results
            item = Dataset()

            # Patient Module
            patient = order.patient
            if patient:
                # Combine first and last name for PatientName
                patient_name = f"{patient.first_name_en} {patient.last_name_en}".strip()
                item.PatientName = patient_name if patient_name else ""
                item.PatientID = patient.mrn if patient.mrn else ""
                item.PatientBirthDate = (
                    patient.dob.strftime("%Y%m%d") if patient.dob else ""
                )
                item.PatientSex = patient.gender if patient.gender else ""
            else:
                item.PatientName = ""
                item.PatientID = ""
                item.PatientBirthDate = ""
                item.PatientSex = ""

            # Scheduled Procedure Step Module
            step = Dataset()
            step.Modality = order.modality.code if order.modality else "OT"
            step.ScheduledStationAETitle = (
                order.room_station.dicom_ae_title if order.room_station else ""
            )

            if order.scheduled_datetime:
                step.ScheduledProcedureStepStartDate = (
                    order.scheduled_datetime.strftime("%Y%m%d")
                )
                step.ScheduledProcedureStepStartTime = (
                    order.scheduled_datetime.strftime("%H%M%S")
                )
            else:
                step.ScheduledProcedureStepStartDate = ""
                step.ScheduledProcedureStepStartTime = "000000"

            step.ScheduledProcedureStepDescription = order.procedure_name_en or ""
            step.ScheduledPerformingPhysicianName = order.referring_physician or ""
            step.ScheduledProcedureStepID = str(order.id)
            step.AccessionNumber = order.accession_number or ""
            step.RequestedProcedureID = order.procedure_code or ""

            item.ScheduledProcedureStepSequence = [step]

            all_items.append(item)

        return all_items
