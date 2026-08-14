import uuid
from datetime import datetime

from django.db import models


class Procedure(models.Model):
    """Database model for radiology procedures that can be managed via admin panel."""

    class ModalityType(models.TextChoices):
        CT = 'CT', 'CT'
        MR = 'MR', 'MR'
        XR = 'XR', 'X-Ray'
        US = 'US', 'Ultrasound'
        NM = 'NM', 'Nuclear Medicine'
        PET = 'PET', 'PET'
        FLUORO = 'FLUORO', 'Fluoroscopy'
        INT = 'INT', 'Interventional'
        OTHER = 'OTHER', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    name_en = models.CharField(max_length=150)
    name_ar = models.CharField(max_length=150, blank=True)
    modality_type = models.CharField(
        max_length=10,
        choices=ModalityType.choices,
        default=ModalityType.OTHER
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['modality_type', 'code']
        indexes = [
            models.Index(fields=['modality_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name_en}"


# DICOM Standard Modality Types (PS3.16 - CID 29)
RADIOLOGY_PROCEDURE_CHOICES = [
    # CT Procedures
    ('CT_HEAD', 'CT Head without contrast'),
    ('CT_HEAD_C', 'CT Head with contrast'),
    ('CT_CHEST', 'CT Chest without contrast'),
    ('CT_CHEST_C', 'CT Chest with contrast'),
    ('CT_ABD', 'CT Abdomen without contrast'),
    ('CT_ABD_C', 'CT Abdomen with contrast'),
    ('CT_PELVIS', 'CT Pelvis without contrast'),
    ('CT_PELVIS_C', 'CT Pelvis with contrast'),
    ('CT_SPINE_C', 'CT Cervical spine with contrast'),
    ('CT_ANGIO', 'CT Angiography'),

    # MR Procedures
    ('MR_BRAIN', 'MRI Brain without contrast'),
    ('MR_BRAIN_C', 'MRI Brain with contrast'),
    ('MR_SPINE_C', 'MRI Cervical spine without contrast'),
    ('MR_SPINE_T', 'MRI Thoracic spine without contrast'),
    ('MR_SPINE_L', 'MRI Lumbar spine without contrast'),
    ('MR_KNEE', 'MRI Knee without contrast'),
    ('MR_SHOULDER', 'MRI Shoulder without contrast'),
    ('MR_JOINT', 'MRI Joint without contrast'),
    ('MR_ANGIO', 'MR Angiography'),

    # X-Ray Procedures
    ('CXR', 'Chest X-Ray'),
    ('XR_SKULL', 'X-Ray Skull'),
    ('XR_RIBS', 'X-Ray Ribs'),
    ('XR_SPINE_C', 'X-Ray Cervical spine'),
    ('XR_SPINE_T', 'X-Ray Thoracic spine'),
    ('XR_SPINE_L', 'X-Ray Lumbar spine'),
    ('XR_PELVIS', 'X-Ray Pelvis'),
    ('XR_HIP', 'X-Ray Hip'),
    ('XR_FEMUR', 'X-Ray Femur'),
    ('XR_KNEE', 'X-Ray Knee'),
    ('XR_TIBIA', 'X-Ray Tibia/Fibula'),
    ('XR_ANKLE', 'X-Ray Ankle'),
    ('XR_FOOT', 'X-Ray Foot'),
    ('XR_SHOULDER', 'X-Ray Shoulder'),
    ('XR_HUMERUS', 'X-Ray Humerus'),
    ('XR_ELBOW', 'X-Ray Elbow'),
    ('XR_FOREARM', 'X-Ray Forearm'),
    ('XR_WRIST', 'X-Ray Wrist'),
    ('XR_HAND', 'X-Ray Hand'),
    ('XR_FINGER', 'X-Ray Finger'),
    ('XR_MAMMO', 'Mammography'),

    # Ultrasound Procedures
    ('US_ABD', 'Ultrasound Abdomen'),
    ('US_PELVIS', 'Ultrasound Pelvis'),
    ('US_OBST', 'Ultrasound Obstetric'),
    ('US_THYROID', 'Ultrasound Thyroid'),
    ('US_BREAST', 'Ultrasound Breast'),
    ('US_SCROTAL', 'Ultrasound Scrotal'),
    ('US_DOPPLER', 'Ultrasound Doppler'),
    ('US_ECHO', 'Echocardiography'),

    # Nuclear Medicine Procedures
    ('NM_BONE', 'Bone Scan'),
    ('NM_CARDIAC', 'Cardiac Stress Test'),
    ('NM_THYROID', 'Thyroid Scan'),
    ('NM_LUNG', 'Lung Perfusion/Ventilation'),
    ('NM_RENAL', 'Renal Scan'),
    ('NM_HEPATOBILIARY', 'Hepatobiliary Scan'),

    # PET Procedures
    ('PET_CT', 'PET-CT Whole Body'),
    ('PET_BRAIN', 'PET Brain'),

    # Fluoroscopy Procedures
    ('FLUORO_BARIUM', 'Barium Swallow/Meal'),
    ('FLUORO_ENEMA', 'Barium Enema'),
    ('FLUORO_IVP', 'IVP/Urogram'),
    ('FLUORO_HSG', 'Hysterosalpingography'),
    ('FLUORO_VCUG', 'VCUG'),

    # Interventional Procedures
    ('INT_BIOPSY', 'Image-guided Biopsy'),
    ('INT_DRAINAGE', 'Image-guided Drainage'),
    ('INT_INJECTION', 'Image-guided Injection'),
]


class ExamOrder(models.Model):
    class Priority(models.TextChoices):
        STAT = "STAT", "Stat"
        URGENT = "URGENT", "Urgent"
        ROUTINE = "ROUTINE", "Routine"

    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Registered"
        SCHEDULED = "SCHEDULED", "Scheduled"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        REPORTED = "REPORTED", "Reported"
        FINALIZED = "FINALIZED", "Finalized"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    facility = models.ForeignKey(
        "core.Facility", on_delete=models.SET_NULL, null=True
    )
    accession_number = models.CharField(max_length=50, db_index=True)
    referring_physician = models.CharField(max_length=150, blank=True)
    modality = models.ForeignKey(
        "core.Modality", on_delete=models.PROTECT, related_name="exam_orders"
    )
    procedure_code = models.CharField(max_length=20)
    procedure_name_en = models.CharField(max_length=150)
    procedure_name_ar = models.CharField(max_length=150, blank=True)
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.ROUTINE
    )
    clinical_indication = models.TextField(blank=True)
    laterality = models.CharField(
        max_length=3,
        choices=[("L", "Left"), ("R", "Right"), ("B", "Bilateral")],
        blank=True,
    )
    body_part = models.CharField(max_length=100, blank=True)
    contrast_required = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.REGISTERED, db_index=True
    )
    scheduled_datetime = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=15)
    room_station = models.ForeignKey(
        "core.Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="exam_orders"
    )
    dicom_study_instance_uid = models.CharField(
        max_length=64, blank=True, db_index=True
    )
    hl7_message_control_id = models.CharField(max_length=100, blank=True)
    billing_status = models.CharField(max_length=20, default="PENDING", db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["accession_number"],
                name="unique_accession_number",
            )
        ]
        indexes = [
            models.Index(fields=["status", "scheduled_datetime"]),
            models.Index(fields=["modality", "priority"]),
            models.Index(fields=["is_deleted"]),
        ]
        ordering = ["-scheduled_datetime"]

    def __str__(self):
        return f"{self.accession_number} | {self.patient.mrn} | {self.modality.code}"

    def soft_delete(self):
        """Mark the order as deleted without removing from database."""
        self.is_deleted = True
        self.deleted_at = datetime.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])
