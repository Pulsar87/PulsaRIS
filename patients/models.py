import uuid

from django.db import models


class Patient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    mrn = models.CharField(max_length=50, db_index=True)
    first_name_en = models.CharField(max_length=100)
    last_name_en = models.CharField(max_length=100)
    first_name_ar = models.CharField(max_length=100, blank=True)
    last_name_ar = models.CharField(max_length=100, blank=True)
    dob = models.DateField()
    gender = models.CharField(
        max_length=1, choices=[("M", "Male"), ("F", "Female"), ("O", "Other")]
    )
    nationality = models.CharField(max_length=3, blank=True)  # ISO 3166-1 alpha-3
    national_id = models.CharField(max_length=50, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    insurance_provider = models.CharField(max_length=150, blank=True)
    insurance_policy_number = models.CharField(max_length=100, blank=True)
    is_deceased = models.BooleanField(default=False)
    consent_data_sharing = models.BooleanField(default=False)
    data_retention_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "mrn"], name="unique_mrn_per_tenant"
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "last_name_en", "first_name_en"]),
            models.Index(fields=["tenant", "national_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.mrn} | {self.first_name_en} {self.last_name_en}"
