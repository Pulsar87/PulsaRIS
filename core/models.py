"""# models.py (shared across tenants or inside tenant schema)
from django.contrib.auth.models import AbstractUser
from django.db import models


class Tenant(models.Model):
    name = models.CharField(max_length=100, unique=True)
    subdomain = models.CharField(max_length=63, unique=True)
    is_active = models.BooleanField(default=True)


class Facility(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="facilities"
    )
    name = models.CharField(max_length=150)
    hl7_facility_id = models.CharField(max_length=50, blank=True)
    dicom_ae_title = models.CharField(max_length=16, unique=True)


class User(AbstractUser):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    role = models.CharField(
        choices=[
            ("ADMIN", "Admin"),
            ("RADIOLOGIST", "Radiologist"),
            ("TECH", "Technician"),
            ("BILLING", "Billing"),
            ("FRONT_DESK", "Front Desk"),
        ]
    )
    is_active = models.BooleanField(default=True)


class Patient(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    mrn = models.CharField(max_length=50, unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    dob = models.DateField()
    gender = models.CharField(
        choices=[("M", "Male"), ("F", "Female"), ("O", "Other")], max_length=1
    )
    contact_phone = models.CharField(max_length=30, blank=True)
    insurance_provider = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ExamOrder(models.Model):
    STATUS_CHOICES = [
        ("REGISTERED", "Registered"),
        ("SCHEDULED", "Scheduled"),
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("REPORTED", "Reported"),
        ("FINALIZED", "Finalized"),
        ("CANCELLED", "Cancelled"),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT)
    ordering_provider = models.CharField(max_length=150)
    modality = models.CharField(
        choices=[
            ("CT", "CT"),
            ("MR", "MRI"),
            ("XR", "X-Ray"),
            ("US", "Ultrasound"),
            ("NM", "Nuclear"),
        ],
        max_length=2,
    )
    procedure_code = models.CharField(max_length=20)
    status = models.CharField(choices=STATUS_CHOICES, default="REGISTERED")
    scheduled_datetime = models.DateTimeField(null=True, blank=True)
    dicom_study_instance_uid = models.CharField(max_length=64, blank=True)
    hl7_message_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Report(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    exam_order = models.OneToOneField(
        ExamOrder, on_delete=models.CASCADE, related_name="report"
    )
    radiologist = models.ForeignKey(
        User, on_delete=models.PROTECT, limit_choices_to={"role": "RADIOLOGIST"}
    )
    findings = models.TextField()
    impression = models.TextField()
    status = models.CharField(
        choices=[
            ("DRAFT", "Draft"),
            ("PRELIMINARY", "Preliminary"),
            ("FINAL", "Final"),
            ("AMENDED", "Amended"),
        ],
        default="DRAFT",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    voice_recording_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=100)  # e.g., 'VIEW_REPORT', 'CHANGE_STATUS'
    target_type = models.CharField(max_length=50)
    target_id = models.PositiveIntegerField()
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(auto_now_add=True)
"""
