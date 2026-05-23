"""
from django.db import models


class Tenant(TenantMixin):
    name = models.CharField(max_length=100, unique=True)
    created_on = models.DateField(auto_now_add=True)
    auto_create_schema = True


"""

import uuid

from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, unique=True)
    subdomain = models.CharField(max_length=63, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
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

    class Domain(DomainMixin):
        pass
