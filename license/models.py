from django.db import models


class LicenseActivation(models.Model):
    expiry_date = models.DateField()
    signature = models.CharField(max_length=8)
    max_orders = models.PositiveIntegerField(null=True, blank=True)
    activated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "license activation"
        verbose_name_plural = "license activation"
