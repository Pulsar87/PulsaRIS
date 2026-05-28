import uuid

from django.db import models


class Report(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PRELIMINARY = "PRELIMINARY", "Preliminary"
        FINAL = "FINAL", "Final"
        AMENDED = "AMENDED", "Amended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    order = models.OneToOneField(
        "orders.ExamOrder", on_delete=models.CASCADE, related_name="report"
    )
    radiologist = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, limit_choices_to={"is_staff": True}
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    findings_en = models.TextField(blank=True)
    findings_ar = models.TextField(blank=True)
    impression_en = models.TextField(blank=True)
    impression_ar = models.TextField(blank=True)
    critical_finding = models.BooleanField(default=False)
    peer_reviewed_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_reports",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    structured_data = models.JSONField(
        blank=True, default=dict
    )  # For templates, measurements, DICOM overlays
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "status", "finalized_at"]),
            models.Index(fields=["tenant", "critical_finding"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Report #{self.id} | {self.order.accession_number} | {self.status}"
