from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LicenseActivation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("expiry_date", models.DateField()),
                ("signature", models.CharField(max_length=8)),
                ("max_orders", models.PositiveIntegerField(blank=True, null=True)),
                ("activated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "license activation",
                "verbose_name_plural": "license activation",
            },
        ),
    ]
