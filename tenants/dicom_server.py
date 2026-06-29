#!/usr/bin/env python
"""
DICOM Modality Worklist SCP Server for Django
Listens for C-FIND requests and returns worklist items from the database.
"""

import os
import sys

import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "config.settings"
)  # Adjust 'config.settings' to your project settings
django.setup()

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pynetdicom import AE, debug_logger, evt
from pynetdicom.status import STATUS_PENDING, STATUS_SUCCESS

from django_tenants.utils import get_tenant_model

from orders.models import ExamOrder  # Import from orders app
from tenants.models import Device, Modality, Tenant  # Import related models


def get_worklist_items(request_dataset):
    """
    Query the database for worklist items matching the request filters.
    Returns a list of Datasets representing worklist items.
    """
    # Extract filters from request
    modality_filter = getattr(request_dataset, "Modality", None)
    station_ae_filter = getattr(request_dataset, "ScheduledStationAETitle", None)
    patient_name_filter = getattr(request_dataset, "PatientName", None)
    patient_id_filter = getattr(request_dataset, "PatientID", None)

    # Build queryset from public schema - ExamOrder has a tenant FK
    queryset = ExamOrder.objects.select_related(
        "patient", "modality", "room_station", "tenant"
    ).filter(status=ExamOrder.Status.SCHEDULED)

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
            ) | queryset.filter(patient__last_name_en__icontains=patient_name_filter)

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
            step.ScheduledProcedureStepStartDate = order.scheduled_datetime.strftime(
                "%Y%m%d"
            )
            step.ScheduledProcedureStepStartTime = order.scheduled_datetime.strftime(
                "%H%M%S"
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


def handle_find(event):
    """
    Handle C-FIND-RQ messages.
    """
    # Access the identifier dataset for C-FIND requests
    try:
        request = event.identifier
    except AttributeError:
        # Fallback for different pynetdicom versions
        request = event.dataset
    
    print(f"\nReceived C-FIND request from {event.association.requestor.ae_title}")
    print(
        f"Filters: Modality={getattr(request, 'Modality', '*')}, "
        f"Station={getattr(request, 'ScheduledStationAETitle', '*')}"
    )

    # Get matching worklist items
    matches = get_worklist_items(request)

    if not matches:
        print("No matching worklist items found.")
        yield (0x0000, None)  # Success with no matches
        return

    print(f"Found {len(matches)} matching worklist items.")

    # Return each match
    for item in matches:
        yield (0xFF00, item)  # Pending (more matches coming)

    yield (0x0000, None)  # Success (no more matches)


def main():
    # Configuration
    AE_TITLE = "RIS_SCP"
    PORT = 11112
    HOST = "0.0.0.0"  # Listen on all interfaces

    # Initialize Application Entity
    ae = AE(ae_title=AE_TITLE)

    # Add supported context for Modality Worklist Information Find
    mwlsop = "1.2.840.10008.5.1.4.31"
    ae.add_supported_context(mwlsop)

    # Define event handlers
    handlers = [(evt.EVT_C_FIND, handle_find)]

    print(f"Starting DICOM Modality Worklist SCP server...")
    print(f"AE Title: {AE_TITLE}")
    print(f"Listening on: {HOST}:{PORT}")
    print("Press Ctrl+C to stop\n")

    # Start server
    try:
        ae.start_server((HOST, PORT), evt_handlers=handlers, block=True)
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
    except Exception as e:
        print(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
