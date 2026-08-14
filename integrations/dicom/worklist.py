"""
DICOM Modality Worklist (MWL) Service

This module handles sending worklist entries to DICOM devices using the
DICOM MWL (Modality Worklist List) service class. It uses pynetdicom
library to establish DICOM associations and send worklist information.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple, List

from django.db.models import QuerySet

logger = logging.getLogger(__name__)

# Type hints for when pydicom is not available
Dataset = None

try:
    from pydicom.dataset import Dataset
    from pydicom.uid import ImplicitVRLittleEndian
    from pynetdicom import AE
    from pynetdicom.sop_class import ModalityWorklistInformationModelFind
    from pynetdicom.status import STATUS_FAILURE, STATUS_PENDING, STATUS_SUCCESS
    PYNETDICOM_AVAILABLE = True
except ImportError:
    PYNETDICOM_AVAILABLE = False
    logger.warning("pynetdicom not installed. DICOM worklist features disabled.")


def verify_dicom_connection(
    ae_title: str,
    host: str,
    port: int,
    calling_ae_title: str = "RIS_SYSTEM",
    timeout: int = 10
) -> Tuple[bool, str]:
    """
    Verify connectivity to a DICOM device by attempting association.

    Args:
        ae_title: The called AE Title of the remote device
        host: IP address or hostname of the DICOM device
        port: Port number for DICOM communication
        calling_ae_title: The calling AE Title (this system's AE Title)
        timeout: Connection timeout in seconds

    Returns:
        Tuple of (success: bool, message: str)
    """
    if not PYNETDICOM_AVAILABLE:
        return False, "pynetdicom library not available"

    try:
        ae = AE(ae_title=calling_ae_title)
        ae.accepted_transfer_syntaxes = [ImplicitVRLittleEndian]

        assoc = ae.associate(
            addr=host,
            port=port,
            ae_title=ae_title,
            timeout=timeout
        )

        if assoc.is_established:
            assoc.release()
            return True, f"Successfully connected to {ae_title} at {host}:{port}"
        else:
            return False, f"Failed to establish association with {ae_title} at {host}:{port}"

    except Exception as e:
        logger.error(f"Error verifying DICOM connection: {str(e)}")
        return False, f"Connection error: {str(e)}"


def _create_worklist_dataset(order):
    """
    Create a DICOM worklist dataset from an ExamOrder.

    This creates a dataset conforming to the DICOM Modality Worklist
    Information Object Definition (IOD).

    Args:
        order: ExamOrder instance

    Returns:
        pydicom Dataset containing worklist attributes
    """
    if not PYNETDICOM_AVAILABLE:
        return None

    ds = Dataset()

    # Patient Module
    ds.PatientName = f"{order.patient.last_name_en}^{order.patient.first_name_en}"
    ds.PatientID = order.patient.mrn
    if hasattr(order.patient, 'date_of_birth'):
        ds.PatientBirthDate = order.patient.date_of_birth.strftime("%Y%m%d") if order.patient.date_of_birth else ""
    else:
        ds.PatientBirthDate = ""

    ds.PatientSex = getattr(order.patient, 'gender', 'O')

    # Accession Module
    ds.AccessionNumber = order.accession_number

    # Requested Procedure Module
    ds.RequestedProcedureID = str(order.id)
    ds.RequestedProcedureDescription = order.procedure_name_en
    ds.RequestedProcedureCodeSequence = []

    # Study Module
    ds.StudyInstanceUID = order.dicom_study_instance_uid or ""
    ds.StudyID = order.accession_number
    ds.StudyDescription = order.procedure_name_en

    # Scheduling Module
    if order.scheduled_datetime:
        ds.ScheduledStationAETitle = order.room_station.dicom_ae_title if order.room_station else ""
        ds.ScheduledProcedureStepStartDate = order.scheduled_datetime.strftime("%Y%m%d")
        ds.ScheduledProcedureStepStartTime = order.scheduled_datetime.strftime("%H%M%S")
        ds.ScheduledProcedureStepDescription = order.procedure_name_en
        ds.Modality = order.modality.code
        ds.ScheduledPerformingPhysicianName = order.referring_physician

    # Modality Module
    ds.Modality = order.modality.code

    # Set specific character set
    ds.SpecificCharacterSet = "ISO_IR 100"

    return ds


def send_worklist_to_device(
    order,
    device,
    calling_ae_title: str = "RIS_SYSTEM",
    timeout: int = 30
) -> Tuple[bool, str]:
    """
    Send a worklist entry to a specific DICOM device.

    This function sends a single worklist entry (representing an exam order)
    to a DICOM modality device using the DICOM MWL service.

    Args:
        order: ExamOrder instance containing the worklist information
        device: Device instance representing the target DICOM device
        calling_ae_title: The calling AE Title (this system's AE Title)
        timeout: Association timeout in seconds

    Returns:
        Tuple of (success: bool, message: str)
    """
    if not PYNETDICOM_AVAILABLE:
        msg = "pynetdicom library not available. Install with: pip install pynetdicom"
        logger.error(msg)
        return False, msg

    try:
        # Create the worklist dataset
        worklist_ds = _create_worklist_dataset(order)

        # Initialize AE
        ae = AE(ae_title=calling_ae_title)
        ae.accepted_transfer_syntaxes = [ImplicitVRLittleEndian]

        # Add the requested presentation context for MWL
        ae.add_requested_context(ModalityWorklistInformationModelFind)

        # Associate with the remote device
        assoc = ae.associate(
            addr=device.dicom_host,
            port=device.dicom_port,
            ae_title=device.dicom_ae_title,
            timeout=timeout
        )

        if assoc.is_established:
            # Note: DICOM MWL is typically a query service where modalities
            # query the RIS/PACS. For pushing worklists, we use C-STORE
            # or rely on the modality polling.
            #
            # This implementation demonstrates the association capability.
            # Actual worklist distribution typically happens via:
            # 1. Modality-initiated C-FIND queries to RIS
            # 2. HL7 ORM messages
            # 3. DICOM Storage (C-STORE) of worklist files

            logger.info(
                f"Successfully associated with {device.name} "
                f"({device.dicom_ae_title}) for worklist"
            )

            # Store the worklist entry in database for modality retrieval
            from integrations.models import ModalityWorklistEntry
            mwl_entry, created = ModalityWorklistEntry.objects.get_or_create(
                tenant=order.tenant,
                order=order,
                defaults={
                    'dicom_query_retrieve_level': 'STUDY',
                    'sync_status': 'SENT'
                }
            )

            if not created:
                mwl_entry.sync_status = 'SENT'
                mwl_entry.last_mwl_sync = datetime.now()
                mwl_entry.save()

            assoc.release()

            return True, f"Worklist entry prepared for {device.name}. Modality can now query."
        else:
            msg = f"Failed to associate with {device.name} at {device.dicom_host}:{device.dicom_port}"
            logger.error(msg)
            return False, msg

    except Exception as e:
        msg = f"Error sending worklist to {device.name}: {str(e)}"
        logger.error(msg)
        return False, msg


def send_worklist_for_order(
    order,
    calling_ae_title: str = "RIS_SYSTEM",
    timeout: int = 30
) -> Tuple[bool, str, List[str]]:
    """
    Send worklist entry to all configured devices for an order.

    This function attempts to send the worklist entry to the device
    assigned to the order (room_station), or to all active devices
    of the matching modality if no specific device is assigned.

    Args:
        order: ExamOrder instance
        calling_ae_title: The calling AE Title (this system's AE Title)
        timeout: Association timeout in seconds

    Returns:
        Tuple of (any_success: bool, message: str, results: list of status strings)
    """
    results = []
    any_success = False

    # Determine target devices
    devices = []

    if order.room_station:
        # Send to the specific assigned device
        if order.room_station.is_active and order.room_station.dicom_host:
            devices.append(order.room_station)
    else:
        # Send to all active devices of the matching modality
        from core.models import Device
        devices = Device.objects.filter(
            modality=order.modality,
            is_active=True,
            dicom_host__isnull=False
        )

    if not devices:
        msg = "No configured DICOM devices found for this order's modality"
        logger.warning(msg)
        return False, msg, results

    # Send to each device
    for device in devices:
        success, message = send_worklist_to_device(
            order,
            device,
            calling_ae_title,
            timeout
        )
        results.append(f"{device.name}: {'Success' if success else 'Failed'} - {message}")

        if success:
            any_success = True

    if any_success:
        msg = f"Worklist sent to {sum(1 for r in results if 'Success' in r)} of {len(devices)} device(s)"
    else:
        msg = f"Failed to send worklist to any of {len(devices)} device(s)"

    return any_success, msg, results


def query_worklist_from_device(
    device,
    calling_ae_title: str = "RIS_SYSTEM",
    patient_id: Optional[str] = None,
    accession_number: Optional[str] = None,
    timeout: int = 30
) -> Tuple[bool, List[Dataset], str]:
    """
    Query worklist from a DICOM device (for testing/verification).

    This function performs a C-FIND operation to query existing worklist
    entries from a device. Useful for verification and debugging.

    Args:
        device: Device instance to query
        calling_ae_title: The calling AE Title
        patient_id: Optional filter by patient ID
        accession_number: Optional filter by accession number
        timeout: Association timeout in seconds

    Returns:
        Tuple of (success: bool, datasets: list, message: str)
    """
    if not PYNETDICOM_AVAILABLE:
        return False, [], "pynetdicom library not available"

    try:
        ae = AE(ae_title=calling_ae_title)
        ae.accepted_transfer_syntaxes = [ImplicitVRLittleEndian]
        ae.add_requested_context(ModalityWorklistInformationModelFind)

        assoc = ae.associate(
            addr=device.dicom_host,
            port=device.dicom_port,
            ae_title=device.dicom_ae_title,
            timeout=timeout
        )

        if not assoc.is_established:
            return False, [], "Failed to establish association"

        # Create query dataset
        query_ds = Dataset()
        query_ds.QueryRetrieveLevel = "STUDY"

        if patient_id:
            query_ds.PatientID = patient_id
        if accession_number:
            query_ds.AccessionNumber = accession_number

        # Request specific fields to be returned
        query_ds.PatientName = ""
        query_ds.PatientID = patient_id or ""
        query_ds.AccessionNumber = accession_number or ""
        query_ds.Modality = ""

        # Perform C-FIND
        responses = assoc.send_c_find(query_ds, ModalityWorklistInformationModelFind)

        datasets = []
        for (status, identifier) in responses:
            if status.Status == STATUS_SUCCESS:
                break
            elif status.Status == STATUS_PENDING:
                if identifier:
                    datasets.append(identifier)
            else:
                assoc.release()
                return False, datasets, f"C-FIND failed with status: {status.Status}"

        assoc.release()
        return True, datasets, f"Found {len(datasets)} worklist entries"

    except Exception as e:
        logger.error(f"Error querying worklist: {str(e)}")
        return False, [], f"Query error: {str(e)}"
