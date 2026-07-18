import uuid

from django.db import models


class HL7MessageLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message_type = models.CharField(max_length=10, db_index=True)  # ADT, ORM, ORU, ACK
    direction = models.CharField(
        max_length=10, choices=[("IN", "Inbound"), ("OUT", "Outbound")]
    )
    raw_content = models.TextField()
    status = models.CharField(max_length=20, default="RECEIVED")
    error_details = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["message_type", "received_at"])]
        ordering = ["-received_at"]


class ModalityWorklistEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(
        "orders.ExamOrder", on_delete=models.CASCADE, related_name="mwl_entry"
    )
    dicom_query_retrieve_level = models.CharField(max_length=20, default="PATIENT")
    last_mwl_sync = models.DateTimeField(null=True, blank=True)
    sync_status = models.CharField(max_length=20, default="PENDING")

    class Meta:
        indexes = [models.Index(fields=["sync_status"])]
