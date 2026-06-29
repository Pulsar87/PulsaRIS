import uuid

from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


# DICOM Standard Modality Types (PS3.16 - CID 29)
DICOM_MODALITY_CHOICES = [
    ('AU', 'Audio'),
    ('BD', 'Biomagnetic Device'),
    ('BI', 'Biosignal'),
    ('CD', 'Confocal Microscopy'),
    ('CR', 'Computed Radiography'),
    ('CT', 'Computed Tomography'),
    ('DG', 'Diaphanography'),
    ('DX', 'Digital Radiography'),
    ('ECG', 'Electrocardiography'),
    ('EPS', 'Cardiac Electrophysiology'),
    ('ES', 'Endoscopy'),
    ('FID', 'Fiducials'),
    ('GM', 'General Microscopy'),
    ('HC', 'Hard Copy'),
    ('HD', 'Hemodynamic Waveform'),
    ('IO', 'Intra-oral Radiography'),
    ('IVUS', 'Intravascular Ultrasound'),
    ('KO', 'Key Object Selection'),
    ('LS', 'Laser Surface Scan'),
    ('MG', 'Mammography'),
    ('MR', 'Magnetic Resonance'),
    ('NM', 'Nuclear Medicine'),
    ('OP', 'Ophthalmic Photography'),
    ('OPM', 'Ophthalmic Mapping'),
    ('OPT', 'Ophthalmic Tomography'),
    ('OSS', 'Optical Surface Scan'),
    ('OT', 'Other'),
    ('PX', 'Panoramic X-Ray'),
    ('PT', 'Positron Emission Tomography'),
    ('RG', 'Radiographic Imaging'),
    ('RF', 'Radio Fluoroscopy'),
    ('RTDOSE', 'Radiotherapy Dose'),
    ('RTIMAGE', 'Radiotherapy Image'),
    ('RTPLAN', 'Radiotherapy Plan'),
    ('RTRECORD', 'Radiotherapy Record'),
    ('RTSTRUCT', 'Radiotherapy Structure Set'),
    ('RWV', 'Real World Value Map'),
    ('SC', 'Secondary Capture'),
    ('SM', 'Slide Microscopy'),
    ('SMR', 'Stereometric Radiography'),
    ('SR', 'Structured Report'),
    ('STAIN', 'Staining'),
    ('TG', 'Thermography'),
    ('US', 'Ultrasound'),
    ('VA', 'Visual Acuity'),
    ('XC', 'External Camera Photography'),
    ('XA', 'X-Ray Angiography'),
]


class Tenant(TenantMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_name = models.CharField(max_length=63, unique=True)
    name = models.CharField(max_length=150, unique=True)
    subdomain = models.CharField(max_length=63, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    license_activated = models.BooleanField(default=False)
    license_expiry = models.DateField(null=True, blank=True)
    license_signature = models.CharField(max_length=255, blank=True)
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
    code = models.CharField(max_length=10, choices=DICOM_MODALITY_CHOICES)
    name = models.CharField(max_length=50, blank=True)
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
    
    # DICOM Network Configuration
    dicom_ae_title = models.CharField(max_length=16, default="DEVICE", help_text="DICOM AE Title of the device")
    dicom_host = models.GenericIPAddressField(help_text="IP address or hostname of the DICOM device")
    dicom_port = models.PositiveIntegerField(default=104, help_text="DICOM port number")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["tenant", "name"]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.modality.code}) - {self.dicom_host}:{self.dicom_port}"


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
