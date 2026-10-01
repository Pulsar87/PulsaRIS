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
from datetime import datetime
from django.core.management.base import BaseCommand
from pydicom.dataset import Dataset
from pynetdicom import AE, evt, debug_logger
from pynetdicom.sop_class import Verification, ModalityWorklistInformationFind, ModalityPerformedProcedureStep

from orders.models import ExamOrder
from core.models import Device, Modality

debug_logger()
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
        handlers = [(evt.EVT_C_FIND, self.handle_find),
                    (evt.EVT_N_CREATE, self.handle_n_create),
                    (evt.EVT_N_SET, self.handle_n_set),
                    ]

        # Add supported contexts
        ae.add_supported_context(Verification)
        ae.add_supported_context(ModalityWorklistInformationFind)
        ae.add_supported_context(ModalityPerformedProcedureStep)

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
            f"Received C-FIND from {event.assoc.requestor.ae_title}: "
           # f"Received C-FIND from {event.association.requestor.ae_title}: "
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
            # step.ScheduledProcedureStepID = str(order.id)
            # step.AccessionNumber = order.accession_number or ""
            # step.RequestedProcedureID = order.procedure_code or ""
            #
            # # SH/AE fields: max 16 chars
            step.ScheduledProcedureStepID = (order.accession_number or str(order.id))[:16]
            step.AccessionNumber = (order.accession_number or "")[:16]
            step.RequestedProcedureID = (order.procedure_code or "")[:16]

            item.ScheduledProcedureStepSequence = [step]

            all_items.append(item)

        return all_items


    def handle_n_create(self, event):
        """
        Handle N-CREATE-RQ messages for MPPS.

        This is called when a modality creates a new MPPS instance,
        indicating the procedure has started.

        Note: For N-CREATE events, pynetdicom provides the dataset via
        event.attribute_list (not event.dataset). The attribute_list is
        a list of (tag, vr, value) tuples.
        """
        # Extract attributes from the attribute_list
        # Format: [(tag, vr, value), ...]
        attribute_list = event.attribute_list if hasattr(event, 'attribute_list') else []

        # Convert attribute_list to a dict for easier access
        attrs = {}
        for tag, vr, value in attribute_list:
            # Tag format: (group, element) - convert to hex string like "00080050"
            tag_hex = f"{tag[0]:04X}{tag[1]:04X}"
            attrs[tag_hex] = value

        # Extract key identifiers using DICOM tags
        # SOPInstanceUID (0008,0018)
        mpps_uid = attrs.get('00080018', '')
        # AccessionNumber (0008,0050) - may be in ScheduledStepAttributesSequence
        accession_number = attrs.get('00080050', '')
        # PerformedProcedureStepID (0040,0253)
        procedure_step_id = attrs.get('00400253', '')
        # PerformedProcedureStepStatus (0040,0275)
        status = attrs.get('00400275', '')

        # Try to extract from ScheduledStepAttributesSequence (0040,0270) if not at root
        if not accession_number and '00400270' in attrs:
            scheduled_seq = attrs['00400270']
            # Sequence items may be passed as nested structures
            if hasattr(scheduled_seq, '__iter__') and not isinstance(scheduled_seq, str):
                try:
                    for item in scheduled_seq:
                        if hasattr(item, 'get'):
                            accession_number = item.get('AccessionNumber', '')
                            if accession_number:
                                break
                        elif isinstance(item, dict):
                            accession_number = item.get('00080050', item.get('AccessionNumber', ''))
                            if accession_number:
                                break
                except (TypeError, AttributeError):
                    pass

        self.stdout.write(
            f"Received N-CREATE (MPPS): MPPS UID={mpps_uid}, "
            f"Accession={accession_number or '*'}, Status={status or 'UNKNOWN'}"
        )

        # Try to find and update the corresponding exam order
        order = None
        if accession_number:
            try:
                order = ExamOrder.objects.get(accession_number=accession_number)
                old_status = order.status

                # Update order status to IN_PROGRESS if it's in an appropriate state
                if order.status in [ExamOrder.Status.REGISTERED, ExamOrder.Status.SCHEDULED]:
                    order.status = ExamOrder.Status.IN_PROGRESS
                    order.mpps_sop_instance_uid = mpps_uid
                    order.save(update_fields=["status", "mpps_sop_instance_uid", "updated_at"])
                    self.stdout.write(
                        f"Updated order {order.id} status: {old_status} -> {order.status}, MPPS UID saved"
                    )
                else:
                    # Just save the MPPS UID even if status doesn't change
                    if not order.mpps_sop_instance_uid:
                        order.mpps_sop_instance_uid = mpps_uid
                        order.save(update_fields=["mpps_sop_instance_uid", "updated_at"])
                        self.stdout.write(f"Saved MPPS UID to order {order.id}")
            except ExamOrder.DoesNotExist:
                self.stdout.write(f"No order found with AccessionNumber: {accession_number}")
            except Exception as e:
                self.stderr.write(f"Error updating order status: {e}")

        # Create response dataset per DICOM standard for N-CREATE
        # Response should contain only attributes that were successfully created
        response = Dataset()
        if mpps_uid:
            response.SOPInstanceUID = mpps_uid
        if procedure_step_id:
            response.PerformedProcedureStepID = procedure_step_id
        if status:
            response.PerformedProcedureStepStatus = status

        # Return success status with response dataset (allowed for N-CREATE)
        return (0x0000, response) if response else 0x0000

    def handle_n_set(self, event):
        """
        Handle N-SET-RQ messages for MPPS.

        This is called when a modality updates an existing MPPS instance,
        typically to indicate procedure completion or status changes.

        Note: For N-SET events, pynetdicom provides the dataset via
        event.attribute_list (not event.dataset). The attribute_list is
        a list of (tag, vr, value) tuples.

        Important: Per DICOM standard, N-SET success response should NOT
        include a dataset - only the status code should be returned.
        """
        # Extract attributes from the attribute_list
        # Format: [(tag, vr, value), ...]
        attribute_list = event.attribute_list if hasattr(event, 'attribute_list') else []

        # Convert attribute_list to a dict for easier access
        attrs = {}
        for tag, vr, value in attribute_list:
            # Tag format: (group, element) - convert to hex string like "00080050"
            tag_hex = f"{tag[0]:04X}{tag[1]:04X}"
            attrs[tag_hex] = value

        # Extract key identifiers using DICOM tags
        # SOPInstanceUID (0008,0018) - this is the MPPS UID being updated
        mpps_uid = attrs.get('00080018', '')
        # AccessionNumber (0008,0050) - may or may not be present in N-SET
        accession_number = attrs.get('00080050', '')
        # PerformedProcedureStepID (0040,0253)
        procedure_step_id = attrs.get('00400253', '')
        # PerformedProcedureStepStatus (0040,0275)
        status = attrs.get('00400275', '')

        self.stdout.write(
            f"Received N-SET (MPPS): MPPS UID={mpps_uid}, "
            f"Accession={accession_number or '*'}, Status={status or 'UNKNOWN'}"
        )

        # Try to find and update the corresponding exam order
        # Priority: use MPPS UID first (most reliable), fallback to AccessionNumber
        order = None
        if mpps_uid:
            try:
                order = ExamOrder.objects.get(mpps_sop_instance_uid=mpps_uid)
            except ExamOrder.DoesNotExist:
                pass

        if not order and accession_number:
            try:
                order = ExamOrder.objects.get(accession_number=accession_number)
                # If we found by accession and have MPPS UID, save it for future lookups
                if mpps_uid and not order.mpps_sop_instance_uid:
                    order.mpps_sop_instance_uid = mpps_uid
                    order.save(update_fields=["mpps_sop_instance_uid", "updated_at"])
            except ExamOrder.DoesNotExist:
                pass

        if order:
            old_status = order.status

            # Map MPPS status to order status
            if status == "COMPLETED":
                if order.status in [
                    ExamOrder.Status.REGISTERED,
                    ExamOrder.Status.SCHEDULED,
                    ExamOrder.Status.IN_PROGRESS,
                ]:
                    order.status = ExamOrder.Status.COMPLETED
                    order.save(update_fields=["status", "updated_at"])
                    self.stdout.write(
                        f"Updated order {order.id} status: {old_status} -> {order.status}"
                    )
            elif status == "DISCONTINUED":
                if order.status != ExamOrder.Status.CANCELLED:
                    order.status = ExamOrder.Status.CANCELLED
                    order.save(update_fields=["status", "updated_at"])
                    self.stdout.write(
                        f"Updated order {order.id} status: {old_status} -> {order.status}"
                    )
            elif status == "IN PROGRESS":
                if order.status in [ExamOrder.Status.REGISTERED, ExamOrder.Status.SCHEDULED]:
                    order.status = ExamOrder.Status.IN_PROGRESS
                    order.save(update_fields=["status", "updated_at"])
                    self.stdout.write(
                        f"Updated order {order.id} status: {old_status} -> {order.status}"
                    )
        else:
            self.stdout.write(
                f"No order found with MPPS UID: {mpps_uid} or AccessionNumber: {accession_number}"
            )

        # Return success status ONLY - no dataset for N-SET per DICOM standard
        return 0x0000
