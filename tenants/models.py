import uuid

from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_name = models.CharField(max_length=63, unique=True)
    name = models.CharField(max_length=150, unique=True)
    subdomain = models.CharField(max_length=63, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    license_activated = models.BooleanField(default=False)
    license_expiry = models.DateField(null=True, blank=True)
    license_signature = models.CharField(max_length=255, blank=True)
    license_max_orders = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum number of orders allowed by license (null for unlimited)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Facility(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="facilities"
    )
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    dicom_ae_title = models.CharField(max_length=16, unique=True)
    hl7_facility_id = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["tenant", "name"]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Modality(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="modalities"
    )
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["tenant", "code"]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="devices"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="devices", null=True, blank=True
    )
    modality = models.ForeignKey(
        Modality, on_delete=models.PROTECT, related_name="devices"
    )
    name = models.CharField(max_length=150)
    room_number = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["tenant", "name"]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.modality.code})"


class Domain(DomainMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="domains", db_index=True
    )
    domain = models.CharField(max_length=253, unique=True, db_index=True)
    is_primary = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["domain"]

    def __str__(self):
        return self.domain
