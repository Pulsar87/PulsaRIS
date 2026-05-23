import uuid

from django.db import models


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
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    facility = models.ForeignKey(
        "tenants.Facility", on_delete=models.SET_NULL, null=True
    )
    accession_number = models.CharField(max_length=50, db_index=True)
    referring_physician = models.CharField(max_length=150, blank=True)
    modality = models.CharField(
        max_length=3,
        choices=[
            ("CT", "CT"),
            ("MR", "MRI"),
            ("XR", "X-Ray"),
            ("US", "Ultrasound"),
            ("NM", "Nuclear"),
            ("DX", "Digital X-Ray"),
        ],
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
    room_station = models.CharField(max_length=50, blank=True)
    dicom_study_instance_uid = models.CharField(
        max_length=64, blank=True, db_index=True
    )
    hl7_message_control_id = models.CharField(max_length=100, blank=True)
    billing_status = models.CharField(max_length=20, default="PENDING", db_index=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "accession_number"],
                name="unique_accession_per_tenant",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "scheduled_datetime"]),
            models.Index(fields=["tenant", "modality", "priority"]),
        ]
        ordering = ["-scheduled_datetime"]

    def __str__(self):
        return f"{self.accession_number} | {self.patient.mrn} | {self.modality}"
