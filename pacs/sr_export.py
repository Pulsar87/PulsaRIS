"""DICOM Structured Report export service (PACS plan Task 5.1).

Rules enforced here (docs/PACS_IMPLEMENTATION.md §5, plan Phase 5):

- Where a report is exported as a DICOM SR associated with an existing
  imaging study, the SR MUST carry the linked
  ``ExamOrder.dicom_study_instance_uid`` (validated) — never a freshly
  generated StudyInstanceUID. The SR gets its own unique
  SeriesInstanceUID/SOPInstanceUID plus a By-Direct Reference to the
  referenced imaging series (Basic Text SR, SOP Class
  1.2.840.10008.5.1.4.1.1.88.11).
- If there is no valid linked imaging study we do NOT silently invent a
  relationship: the export is blocked with a clear message until the
  order/study link exists (MWL assignment or manual reconciliation in
  the PACS UI). This is the documented policy for this deployment;
  standalone-SR export is not offered because it would produce reports
  unattributable to any imaging study.
- Signed/finalized report text is copied verbatim into the content
  sequence; nothing mutates it.
- All raw REST access goes through ``pacs.orthanc_client.OrthancClient``.

The view layer stays thin: it resolves facility-scoped objects, calls
``build_sr_dataset`` / ``store_sr_for_report`` here, and surfaces errors
as messages (never crashing the request).
"""

import logging
from io import BytesIO

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from pacs.dicom_uid import clean_dicom_uid, is_valid_dicom_uid
from pacs.models import PACSStudy
from pacs.orthanc_client import OrthancClient, OrthancError

logger = logging.getLogger(__name__)

BASIC_TEXT_SR_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.88.11"

# Committed human-readable identity of this generator (Task 5.1 requires
# stable, honest source information instead of the old fabricated values).
SR_MANUFACTURER = "Pulsar RIS"
SR_DEVICE_SERIAL_NUMBER = "RIS-SR"
SR_STATION_NAME = "PULSAR_RIS"
SR_OPERATOR_NAME = "Pulsar RIS"


class SRLinkageError(Exception):
    """No valid imaging-study linkage exists for this report (Task 5.1).

    ``message`` is safe to show to the exporting user; it contains only
    identifiers already visible to them within their facility scope.
    """

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def resolve_linked_study(order):
    """Return the validated StudyInstanceUID linked to *order*, else ''.

    Preference order (all sources are trusted RIS-side records, never
    arbitrary tags from the export request):
    1. ExamOrder.dicom_study_instance_uid (set by MWL UID assignment,
       Task 3.2, or manual reconciliation);
    2. a PACSStudy mirror row matched to the order whose stored UID is
       syntactically valid.
    Invalid/blank UIDs yield '' — callers must treat that as
    "no linkage", not as "invent one".
    """
    uid = clean_dicom_uid(getattr(order, "dicom_study_instance_uid", ""))
    if uid and is_valid_dicom_uid(uid):
        return uid
    study = (
        PACSStudy.objects.filter(matched_order=order)
        .order_by("-last_received_at", "-created_at")
        .first()
    )
    if study is not None:
        uid = clean_dicom_uid(study.study_instance_uid)
        if is_valid_dicom_uid(uid):
            return uid
    return ""


def _code(concept, value, scheme, meaning):
    item = Dataset()
    item.CodeValue = value
    item.CodingSchemeDesignator = scheme
    item.CodeMeaning = meaning
    setattr(concept, "ConceptNameCodeSequence", [item])
    return concept


def build_sr_dataset(report, study_uid):
    """Build a Basic Text SR dataset linked to *study_uid*.

    Raises SRLinkageError if *study_uid* is missing/invalid (defense in
    depth — the view checks first). Returns a pydicom FileDataset ready
    to serialize; report text is embedded verbatim.
    """
    study_uid = clean_dicom_uid(study_uid)
    if not study_uid or not is_valid_dicom_uid(study_uid):
        raise SRLinkageError(
            "This report's order has no valid linked imaging study; "
            "export is blocked until the study is linked."
        )

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.9.7341.1.1"
    file_meta.ImplementationVersionName = "PULSARRIS_1"

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

    # --- Linkage: THE imaging study's UID, never a fresh one (Task 5.1) ---
    ds.StudyInstanceUID = study_uid
    # New, unique identifiers for the SR itself, as required.
    ds.SeriesInstanceUID = generate_uid()

    order = report.order
    patient = order.patient

    # --- Patient module (must match the order/patient exactly) -----------
    name = f"{patient.last_name_en}^{patient.first_name_en}" if (
        patient.last_name_en or patient.first_name_en
    ) else ""
    ds.PatientName = name
    ds.PatientID = patient.mrn or ""
    ds.PatientBirthDate = patient.dob.strftime("%Y%m%d") if patient.dob else ""
    gender = (patient.gender or "").strip().upper()[:1]
    ds.PatientSex = gender if gender in ("M", "F", "O") else ""

    # --- General Study / Equipment modules -------------------------------
    ds.AccessionNumber = order.accession_number or ""
    ds.StudyID = order.accession_number or ""
    ds.StudyDescription = order.procedure_name_en or "Radiology Report"
    if order.scheduled_datetime:
        ds.StudyDate = order.scheduled_datetime.strftime("%Y%m%d")
        ds.StudyTime = order.scheduled_datetime.strftime("%H%M%S")
    else:
        ds.StudyDate = report.created_at.strftime("%Y%m%d")
        ds.StudyTime = report.created_at.strftime("%H%M%S")
    ds.InstitutionName = (
        getattr(order.facility, "name", "") if getattr(order, "facility_id", None) else ""
    )
    ds.Modality = "SR"
    ds.SeriesNumber = "1"
    ds.SeriesDescription = "Radiology Report"
    ds.Manufacturer = SR_MANUFACTURER
    ds.DeviceSerialNumber = SR_DEVICE_SERIAL_NUMBER
    ds.StationName = SR_STATION_NAME
    ds.OperatorName = SR_OPERATOR_NAME
    completion = "PARTIAL" if not (report.findings_en and report.impression_en) else "COMPLETE"
    ds.CompletionFlag = completion
    ds.VerificationFlag = "UNVERIFIED"
    ds.ContentDate = timezone_datestr(report)
    ds.ContentTime = timezone_timestr(report)

    # --- Referenced study sequence (required for association with the
    #     imaging study). Referenced series/instance come from the mirror
    #     when available; the study-level reference alone still satisfies
    #     the "identifies the same study" acceptance criterion. ----------
    ref_study = Dataset()
    ref_study.ReferencedStudyInstanceUID = study_uid
    mirror = PACSStudy.objects.filter(study_instance_uid=study_uid).first()
    if mirror is not None and mirror.orthanc_study_id:
        series_items = []
        try:
            client = OrthancClient()
            orthanc_series = client.get_series_ids(mirror.orthanc_study_id)
        except OrthancError as exc:
            logger.warning("SR export: archive lookup failed for %s: %s", study_uid, exc)
            orthanc_series = []
        for sid in orthanc_series[:1]:
            try:
                series_uid = clean_dicom_uid(client.get_series_main_dicom_id(sid))
                inst_items = []
                for inst_id in client.get_series_instance_ids(sid)[:1]:
                    inst_meta = client.get_instance_metadata(inst_id)
                    sop_uid = clean_dicom_uid((inst_meta or {}).get("0008,0018", ""))
                    sop_class = clean_dicom_uid((inst_meta or {}).get("0008,0016", ""))
                    if is_valid_dicom_uid(sop_uid):
                        inst = Dataset()
                        inst.ReferencedSOPClassUID = sop_class or "1.2.840.10008.5.1.4.1.1.1"
                        inst.ReferencedSOPInstanceUID = sop_uid
                        inst_items.append(inst)
            except OrthancError:
                continue
            if not is_valid_dicom_uid(series_uid):
                continue
            sref = Dataset()
            sref.ReferencedSeriesInstanceUID = series_uid
            if inst_items:
                sref.ReferencedSOPSequence = inst_items
            series_items.append(sref)
        if series_items:
            ref_study.ReferencedSeriesSequence = series_items
    ds.ReferencedStudySequence = [ref_study]

    # --- Content tree (verbatim signed text; never mutated) --------------
    root = Dataset()
    root.RelationshipType = "CONTAINS"
    root.ValueType = "CONTAINER"
    _code(root, "113014", "DCM", "Imaging Report")
    root.ContinuityOfContent = "SEPARATE"

    items = []
    if report.findings_en:
        item = Dataset()
        item.RelationshipType = "CONTAINS"
        item.ValueType = "TEXT"
        _code(item, "113016", "DCM", "Findings")
        item.TextValue = report.findings_en
        items.append(item)
    if report.impression_en:
        item = Dataset()
        item.RelationshipType = "CONTAINS"
        item.ValueType = "TEXT"
        _code(item, "113017", "DCM", "Conclusion")
        item.TextValue = report.impression_en
        items.append(item)
    if not items:
        item = Dataset()
        item.RelationshipType = "CONTAINS"
        item.ValueType = "TEXT"
        _code(item, "113016", "DCM", "Findings")
        item.TextValue = "No report content available."
        items.append(item)
    root.ContentSequence = items
    ds.ContentSequence = [root]
    return ds


def timezone_datestr(report):
    from django.utils import timezone as tz

    dt = report.finalized_at or report.created_at
    if tz.is_naive(dt):
        dt = tz.make_aware(dt)
    return dt.strftime("%Y%m%d")


def timezone_timestr(report):
    from django.utils import timezone as tz

    dt = report.finalized_at or report.created_at
    if tz.is_naive(dt):
        dt = tz.make_aware(dt)
    return dt.strftime("%H%M%S.%f")[:-3]


def serialize_sr(ds):
    buffer = BytesIO()
    ds.save_as(buffer, write_like_original=False)
    buffer.seek(0)
    return buffer.read()


def store_sr_for_report(report):
    """Build + submit the SR for *report*; returns (bytes, orthanc_id).

    Raises SRLinkageError (blocked export, documented policy) or
    OrthancError on archive failures.
    """
    study_uid = resolve_linked_study(report.order)
    if not study_uid:
        raise SRLinkageError(
            "Cannot export this report as DICOM SR: the order "
            f"{report.order.accession_number or report.order.id} has no linked "
            "imaging study (StudyInstanceUID) yet. Complete image receipt and "
            "link the study via the PACS studies screen (or wait for automatic "
            "matching), then export again. Standalone SR export is disabled by "
            "policy so reports are never attributed to invented studies."
        )
    ds = build_sr_dataset(report, study_uid)
    data = serialize_sr(ds)
    orthanc_id = ""
    try:
        orthanc_id = OrthancClient().submit_instance(data)
    except OrthancError as exc:
        # Downloadable file remains correct; record the failed auto-store.
        logger.warning("SR export: archive store failed for report %s: %s", report.id, exc)
    return data, orthanc_id
